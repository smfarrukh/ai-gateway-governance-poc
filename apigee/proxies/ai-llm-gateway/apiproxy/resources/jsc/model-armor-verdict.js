/*
 * AI LLM gateway - reads the Model Armor sanitizeUserPrompt result and
 * blocks the request if any filter matched (prompt injection / jailbreak,
 * sensitive data, responsible-AI categories, malicious URLs).
 */
(function () {
  // POC default: if Model Armor itself is unreachable, let traffic through but
  // record it. Set to true for production-style fail-closed behaviour.
  var FAIL_CLOSED = false;

  var status = String(context.getVariable('modelArmorResponse.status.code') || '');
  var raw = context.getVariable('modelArmorResponse.content');

  if (status !== '200' || !raw) {
    context.setVariable('llm.armor_state', 'unavailable:' + (status || 'no_response'));
    if (FAIL_CLOSED) {
      context.setVariable('llm.denied', 'true');
      context.setVariable('gw.decision', 'denied:safety_check_unavailable');
      context.setVariable('gw.deny_body', JSON.stringify({
        error: { type: 'policy_violation', code: 'safety_check_unavailable',
                 message: 'Prompt safety screening is unavailable, request refused' }
      }));
    }
    return;
  }

  var result = {};
  try {
    result = JSON.parse(raw).sanitizationResult || {};
  } catch (e) {
    context.setVariable('llm.armor_state', 'unparseable');
    return;
  }

  if (result.filterMatchState !== 'MATCH_FOUND') {
    context.setVariable('llm.armor_state', 'clean');
    return;
  }

  // filterResults is a map of filter name -> nested result carrying matchState.
  var reasons = [];
  var filters = result.filterResults || {};
  for (var name in filters) {
    if (filters.hasOwnProperty(name) && JSON.stringify(filters[name]).indexOf('"MATCH_FOUND"') >= 0) {
      reasons.push(name);
    }
  }

  context.setVariable('llm.armor_state', 'blocked');
  context.setVariable('llm.armor_reasons', reasons.join(','));
  context.setVariable('llm.denied', 'true');
  context.setVariable('gw.decision', 'denied:prompt_blocked');
  context.setVariable('gw.deny_status', '400');
  context.setVariable('gw.deny_body', JSON.stringify({
    error: {
      type: 'policy_violation',
      code: 'prompt_blocked',
      message: 'Blocked by AI gateway safety policy (Model Armor): ' + reasons.join(', '),
      filters: reasons,
      agent: context.getVariable('gw.agent')
    }
  }));
})();
