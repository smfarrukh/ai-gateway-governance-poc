/*
 * AI tools gateway - request guard. Runs right after VerifyAPIKey.
 *
 * Works out which system of record is being called (ServiceNow MCP,
 * Salesforce MCP or the knowledge-base REST tool) and, for MCP
 * "tools/call" requests, checks the tool name against the agent's
 * tool allowlist. Denied MCP calls get a normal MCP tool result with
 * isError=true, so the agent can explain the refusal to its user.
 */
(function () {
  var KEY_POLICY = 'VK-VerifyAgentKey';

  function productAttr(name, fallback) {
    var value = context.getVariable('verifyapikey.' + KEY_POLICY + '.apiproduct.' + name);
    return (value === null || value === undefined || String(value) === '') ? fallback : String(value);
  }

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

  function deny(status, reason, bodyObject) {
    context.setVariable('tool.denied', 'true');
    context.setVariable('gw.decision', 'denied:' + reason);
    context.setVariable('gw.deny_status', String(status));
    context.setVariable('gw.deny_body', JSON.stringify(bodyObject));
  }

  var agent = context.getVariable('developer.app.name') || 'unknown';
  var allowedTools = productAttr('allowed_tools', '');
  context.setVariable('gw.agent', agent);
  context.setVariable('gw.agent_cloud', productAttr('agent_cloud', 'unknown'));
  context.setVariable('gw.decision', 'allowed');
  context.setVariable('tool.denied', 'false');
  context.setVariable('tool.allowed_tools', allowedTools);
  context.setVariable('tool.pii_access', productAttr('pii_access', 'false'));

  var suffix = context.getVariable('proxy.pathsuffix') || '';
  var system = '';
  var protocol = '';
  if (/^\/mcp\/servicenow\/?$/.test(suffix)) { system = 'servicenow'; protocol = 'mcp'; }
  else if (/^\/mcp\/salesforce\/?$/.test(suffix)) { system = 'salesforce'; protocol = 'mcp'; }
  else if (/^\/kb\/search\/?$/.test(suffix)) { system = 'knowledge-base'; protocol = 'rest'; }
  context.setVariable('tool.system', system);
  context.setVariable('tool.protocol', protocol);

  if (!system) {
    deny(404, 'unknown_tool_endpoint', { error: { type: 'not_found', message: 'No governed tool at ' + suffix } });
    return;
  }

  if (protocol === 'rest') {
    context.setVariable('tool.name', 'kb_search');
    if (!allowed(allowedTools, 'kb_search')) {
      deny(403, 'tool_not_allowed', { error: { type: 'policy_violation', code: 'tool_not_allowed',
        message: 'Tool kb_search is not approved for agent ' + agent } });
    }
    return;
  }

  // MCP (JSON-RPC 2.0). GET/DELETE carry no body and pass straight through.
  if (context.getVariable('request.verb') !== 'POST') return;

  var payload;
  try {
    payload = JSON.parse(context.getVariable('request.content') || '{}');
  } catch (e) {
    deny(400, 'invalid_json', { jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Parse error' } });
    return;
  }

  var batch = (payload instanceof Array) ? payload : [payload];
  context.setVariable('mcp.method', batch.length ? String(batch[0].method || '') : '');

  for (var i = 0; i < batch.length; i++) {
    var msg = batch[i] || {};
    if (msg.method !== 'tools/call') continue;
    var toolName = String((msg.params && msg.params.name) || '');
    context.setVariable('tool.name', toolName);
    if (!allowed(allowedTools, toolName)) {
      deny(200, 'tool_not_allowed', {
        jsonrpc: '2.0',
        id: msg.id === undefined ? null : msg.id,
        result: {
          isError: true,
          content: [{
            type: 'text',
            text: 'ACCESS DENIED by the enterprise AI gateway: agent "' + agent + '" is not approved to use tool "' +
                  toolName + '". Tell the user this action needs an approved agent or a human.'
          }]
        }
      });
      return;
    }
  }
})();
