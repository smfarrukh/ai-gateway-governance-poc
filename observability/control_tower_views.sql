-- AI Governance Control Tower - BigQuery views over the gateway audit log.
-- The Cloud Logging sink (walkthrough step 9) writes to ai_governance.ai_gateway_audit.
-- Replace PROJECT_ID below (the walkthrough does this for you), then run the whole file in BigQuery.
-- Run the governance demo first: BigQuery only creates a column once a log entry has carried that field.

CREATE OR REPLACE VIEW `PROJECT_ID.ai_governance.v_gateway_events` AS
SELECT
  timestamp,
  jsonPayload.gateway                                  AS gateway,
  jsonPayload.agent                                    AS agent,
  jsonPayload.agent_cloud                              AS agent_cloud,
  jsonPayload.api_product                              AS api_product,
  SAFE_CAST(jsonPayload.status AS INT64)               AS http_status,
  jsonPayload.decision                                 AS decision,
  STARTS_WITH(jsonPayload.decision, 'denied')          AS is_denied,
  SAFE_CAST(jsonPayload.latency_ms AS INT64)           AS latency_ms,
  jsonPayload.llm.model                                AS model,
  jsonPayload.llm.backend                              AS model_cloud,
  SAFE_CAST(jsonPayload.llm.prompt_tokens AS INT64)    AS prompt_tokens,
  SAFE_CAST(jsonPayload.llm.completion_tokens AS INT64) AS completion_tokens,
  SAFE_CAST(jsonPayload.llm.total_tokens AS INT64)     AS total_tokens,
  jsonPayload.llm.safety_check                         AS safety_check,
  jsonPayload.llm.safety_filters                       AS safety_filters,
  jsonPayload.tool.system                              AS tool_system,
  jsonPayload.tool.mcp_method                          AS mcp_method,
  jsonPayload.tool.name                                AS tool_name,
  jsonPayload.tool.pii_masked                          AS pii_masked,
  SAFE_CAST(jsonPayload.tool.hidden_tools AS INT64)    AS hidden_tools,
  jsonPayload.request_id                               AS request_id
FROM `PROJECT_ID.ai_governance.ai_gateway_audit`;

-- One row per day / agent: volume, denials, tokens.
CREATE OR REPLACE VIEW `PROJECT_ID.ai_governance.v_agent_daily` AS
SELECT
  DATE(timestamp)                         AS day,
  agent,
  agent_cloud,
  COUNT(*)                                AS requests,
  COUNTIF(gateway = 'ai-llm-gateway')     AS llm_calls,
  COUNTIF(tool_name IS NOT NULL)          AS tool_calls,
  COUNTIF(is_denied)                      AS denied,
  SUM(IFNULL(total_tokens, 0))            AS tokens,
  COUNTIF(pii_masked)                     AS pii_masked_responses,
  APPROX_QUANTILES(latency_ms, 100)[OFFSET(95)] AS p95_latency_ms
FROM `PROJECT_ID.ai_governance.v_gateway_events`
GROUP BY day, agent, agent_cloud;

-- Every blocked action, with the reason.
CREATE OR REPLACE VIEW `PROJECT_ID.ai_governance.v_policy_violations` AS
SELECT
  timestamp, agent, agent_cloud, gateway, decision,
  REGEXP_EXTRACT(decision, r'denied:(.*)') AS violation,
  model, tool_system, tool_name, safety_filters, http_status
FROM `PROJECT_ID.ai_governance.v_gateway_events`
WHERE is_denied;

-- Token consumption by agent and model/cloud (the cost driver).
CREATE OR REPLACE VIEW `PROJECT_ID.ai_governance.v_token_usage` AS
SELECT
  DATE(timestamp) AS day, agent, agent_cloud, model, model_cloud,
  COUNT(*) AS calls,
  SUM(IFNULL(prompt_tokens, 0))     AS prompt_tokens,
  SUM(IFNULL(completion_tokens, 0)) AS completion_tokens,
  SUM(IFNULL(total_tokens, 0))      AS total_tokens
FROM `PROJECT_ID.ai_governance.v_gateway_events`
WHERE gateway = 'ai-llm-gateway' AND NOT is_denied
GROUP BY day, agent, agent_cloud, model, model_cloud;

-- Which agent uses which system-of-record tool.
CREATE OR REPLACE VIEW `PROJECT_ID.ai_governance.v_tool_usage` AS
SELECT
  DATE(timestamp) AS day, agent, agent_cloud, tool_system, tool_name,
  COUNT(*)                AS calls,
  COUNTIF(is_denied)      AS denied,
  COUNTIF(pii_masked)     AS pii_masked
FROM `PROJECT_ID.ai_governance.v_gateway_events`
WHERE tool_name IS NOT NULL
GROUP BY day, agent, agent_cloud, tool_system, tool_name;
