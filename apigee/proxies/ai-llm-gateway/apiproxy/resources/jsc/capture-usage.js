/*
 * AI LLM gateway - reads token usage from the model response (plain JSON or
 * a buffered server-sent-events stream) so the token quota can be charged
 * and the audit log can record cost drivers.
 */
(function () {
  var body = context.getVariable('response.content') || '';

  function last(field) {
    var re = new RegExp('"' + field + '"\\s*:\\s*(\\d+)', 'g');
    var match, value = 0;
    while ((match = re.exec(body)) !== null) value = parseInt(match[1], 10);
    return value;
  }

  var prompt = last('prompt_tokens');
  var completion = last('completion_tokens');
  var total = last('total_tokens') || (prompt + completion);

  context.setVariable('llm.prompt_tokens', String(prompt));
  context.setVariable('llm.completion_tokens', String(completion));
  context.setVariable('llm.total_tokens', String(total));

  context.setVariable('response.header.x-ai-gateway-agent', context.getVariable('gw.agent'));
  context.setVariable('response.header.x-ai-gateway-backend', context.getVariable('llm.backend'));
  context.setVariable('response.header.x-ai-gateway-tokens', String(total));
})();
