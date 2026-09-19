/*
 * AI LLM gateway - request guard. Runs right after VerifyAPIKey.
 *
 * 1. Reads the agent's governance profile from its API product attributes.
 * 2. Checks the requested model against the agent's model allowlist.
 * 3. Picks the backend cloud from the model name (routing).
 * 4. Collects the newest untrusted text (user prompt + tool results) so
 *    Model Armor can screen it for prompt injection, jailbreaks and PII.
 *
 * Apigee JavaScript is ES5: no let/const, arrow functions or template strings.
 */
(function () {
  var KEY_POLICY = 'VK-VerifyAgentKey';
  var MAX_SCAN_CHARS = 20000;

  function productAttr(name, fallback) {
    var value = context.getVariable('verifyapikey.' + KEY_POLICY + '.apiproduct.' + name);
    return (value === null || value === undefined || String(value) === '') ? fallback : String(value);
  }

  // "gemini-*,gpt-5-mini" style allowlists. "*" allows everything.
  function allowed(list, value) {
    var patterns = String(list || '').split(',');
    for (var i = 0; i < patterns.length; i++) {
      var p = patterns[i].replace(/^\s+|\s+$/g, '');
      if (!p) continue;
      var re = new RegExp('^' + p.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*') + '$', 'i');
      if (re.test(value)) return true;
    }
    return false;
  }

  function textOf(content) {
    if (content === null || content === undefined) return '';
    if (typeof content === 'string') return content;
    var out = [];
    for (var i = 0; i < content.length; i++) {
      var part = content[i];
      if (typeof part === 'string') out.push(part);
      else if (part && typeof part.text === 'string') out.push(part.text);
    }
    return out.join('\n');
  }

  function deny(status, reason, message) {
    context.setVariable('llm.denied', 'true');
    context.setVariable('gw.decision', 'denied:' + reason);
    context.setVariable('gw.deny_status', String(status));
    context.setVariable('gw.deny_body', JSON.stringify({
      error: { type: 'policy_violation', code: reason, message: message, agent: context.getVariable('gw.agent') }
    }));
  }

  context.setVariable('llm.denied', 'false');
  context.setVariable('llm.scan_length', '0');
  context.setVariable('gw.decision', 'allowed');
  context.setVariable('gw.agent', context.getVariable('developer.app.name') || 'unknown');
  context.setVariable('gw.agent_cloud', productAttr('agent_cloud', 'unknown'));
  context.setVariable('gw.token_quota', productAttr('token_quota_per_hour', '10000'));

  var body;
  try {
    body = JSON.parse(context.getVariable('request.content') || '{}');
  } catch (e) {
    deny(400, 'invalid_json', 'Request body is not valid JSON');
    return;
  }

  var model = String(body.model || '');
  var backend = '';
  if (/^(google\/)?gemini/i.test(model)) backend = 'vertex';
  else if (/^(bedrock\/|openai\.gpt-oss)/i.test(model) || /^[a-z]+\.[a-z0-9]/i.test(model)) backend = 'bedrock';
  else if (/^(gpt-|o\d)/i.test(model)) backend = 'azure';

  context.setVariable('llm.model', model);
  context.setVariable('llm.backend', backend);
  context.setVariable('llm.stream', String(body.stream === true));

  if (!model) {
    deny(400, 'model_missing', 'The request must name a model');
    return;
  }
  if (!allowed(productAttr('allowed_models', ''), model)) {
    deny(403, 'model_not_allowed', 'Model "' + model + '" is not approved for this agent');
    return;
  }
  if (!backend) {
    deny(400, 'unknown_model', 'The gateway has no backend route for model "' + model + '"');
    return;
  }

  // Newest untrusted content = trailing user/tool messages after the last assistant turn.
  var messages = body.messages || [];
  var scan = [];
  for (var i = messages.length - 1; i >= 0; i--) {
    var role = messages[i] && messages[i].role;
    if (role !== 'user' && role !== 'tool') break;
    scan.unshift(textOf(messages[i].content));
  }
  var scanText = scan.join('\n').substring(0, MAX_SCAN_CHARS);
  context.setVariable('llm.scan_length', String(scanText.length));
  context.setVariable('llm.armor_payload', JSON.stringify({ userPromptData: { text: scanText } }));
})();
