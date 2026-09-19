import os

from bedrock_agentcore.identity.auth import requires_api_key
from strands.models.openai import OpenAIModel

# Created by `agentcore create --name salesagent --model-provider OpenAI --api-key <agent key>`.
# The "OpenAI" provider here just means "OpenAI-compatible API" - the endpoint is the Apigee gateway.
IDENTITY_PROVIDER_NAME = "salesagentOpenAI"
IDENTITY_ENV_VAR = "AGENTCORE_CREDENTIAL_SALESAGENTOPENAI"


@requires_api_key(provider_name=IDENTITY_PROVIDER_NAME)
def _agentcore_identity_api_key_provider(api_key: str) -> str:
    """Fetch the Apigee agent key from AgentCore Identity."""
    return api_key


def get_gateway_key() -> str:
    """AgentCore Identity when deployed; agentcore/.env.local when running `agentcore dev`."""
    if os.getenv("LOCAL_DEV") == "1" or os.getenv(IDENTITY_ENV_VAR):
        api_key = os.getenv(IDENTITY_ENV_VAR)
        if not api_key:
            raise RuntimeError(f"{IDENTITY_ENV_VAR} not set; add it to agentcore/.env.local")
        return api_key
    return _agentcore_identity_api_key_provider()


def gateway_url() -> str:
    return os.environ["AI_GATEWAY_URL"].rstrip("/")


def load_model(key: str) -> OpenAIModel:
    """Amazon Bedrock model, reached through the Apigee AI gateway (OpenAI-compatible)."""
    return OpenAIModel(
        client_args={
            "api_key": key,
            "base_url": f"{gateway_url()}/ai/llm/v1",
            "default_headers": {"x-api-key": key},
        },
        model_id=os.environ.get("LLM_MODEL", "openai.gpt-oss-120b"),
    )
