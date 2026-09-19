/*
 * AI LLM gateway - adapts the OpenAI-style request to the chosen backend.
 * Agents always send one format; small per-cloud differences are fixed here.
 */
(function () {
  var backend = context.getVariable('llm.backend');
  var body = JSON.parse(context.getVariable('request.content'));

  function flatten(content) {
    if (!content || typeof content === 'string') return content;
    var text = [];
    for (var i = 0; i < content.length; i++) {
      if (!content[i] || content[i].type !== 'text') return content; // keep images etc. untouched
      text.push(content[i].text);
    }
    return text.join('\n');
  }

  if (backend === 'vertex') {
    // Vertex AI's OpenAI-compatible endpoint expects "google/<model>".
    if (body.model.indexOf('google/') !== 0) body.model = 'google/' + body.model;
  } else if (backend === 'bedrock') {
    body.model = body.model.replace(/^bedrock\//, '');
    // Bedrock Mantle only accepts plain-string content for some roles.
    var messages = body.messages || [];
    for (var i = 0; i < messages.length; i++) {
      messages[i].content = flatten(messages[i].content);
    }
  }
  // Azure OpenAI: the model name is the deployment name, sent as-is.

  context.setVariable('request.content', JSON.stringify(body));
})();
