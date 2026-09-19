/*
 * AI tools gateway - response governance for MCP servers.
 *  - tools/list : hides tools the agent is not approved to use.
 *  - tools/call : masks emails and phone numbers unless the agent is
 *                 approved for personal data (pii_access=true).
 */
(function () {
  var method = context.getVariable('mcp.method');
  var body = context.getVariable('response.content');
  if (!body) return;

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

  var changed = false;

  if (method === 'tools/list') {
    try {
      var listing = JSON.parse(body);
      if (listing.result && listing.result.tools) {
        var allowedTools = context.getVariable('tool.allowed_tools');
        var visible = [];
        for (var i = 0; i < listing.result.tools.length; i++) {
          if (allowed(allowedTools, listing.result.tools[i].name)) visible.push(listing.result.tools[i]);
        }
        context.setVariable('tool.hidden_count', String(listing.result.tools.length - visible.length));
        listing.result.tools = visible;
        body = JSON.stringify(listing);
        changed = true;
      }
    } catch (e) {
      // Not plain JSON (e.g. an SSE stream): leave it; tools/call is still enforced.
    }
  }

  if (method === 'tools/call' && context.getVariable('tool.pii_access') !== 'true') {
    var masked = body
      .replace(/([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})/g, '$1***@$2')
      .replace(/\+\d[\d ().-]{7,}\d/g, '[REDACTED-PHONE]');
    if (masked !== body) {
      body = masked;
      changed = true;
      context.setVariable('tool.pii_masked', 'true');
    }
  }

  if (changed) context.setVariable('response.content', body);
})();
