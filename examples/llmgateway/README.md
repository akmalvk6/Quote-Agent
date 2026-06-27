# LLM Gateway

## Introduction

Every developer and team that builds a GenAI solution or product needs to implement a set of common NFRs in order to track performance, reduce costs, and be well-rounded for enterprise deployments. Built on top of Open Source technologies, DEP AI's LLM Gateway approach aims to simplify the implementation for asset teams by providing easily integratable components that take care of the following functionality:

- **Routing** - We provide the ability to configure and route your requests to any LLM required with a simple API (conforms to OpenAI API) using LiteLLM. LLM Gateway supports multiple LLM providers including OpenAI, Azure OpenAI, AWS Bedrock, Google Cloud Gemini, and even hosting your own LLMs.
- **Virtual Keys** - Create virtual keys with fine-grained access controls to decide which users/system components have access to which LLMs without exposing the underlying secrets.
- **Caching** - Integrate a caching layer to reduce the number of calls to the LLMs and improve the performance of your application while reducing costs. We support both Simple and Semantic caching with Redis.
- **Tracing** - Track and trace all your LLM calls, monitor requests and responses, and track cost and latencies of your LLM usage using Langfuse.

![LLM Gateway Overview](images/high-level-overview.png "LLM Gateway Overview")

## Getting Started

`Recommended Configuration : 8-core , 32 GB RAM`

## Components:

Listed below are some of the LLM Gateway components that are configured in this dev container and the credentials to access them for this demonstration.

| S.No. | Component | Port | Notes |
|----------:|:----------|:----------|:----------|
| 1   | LiteLLM   | 4000 | Used as the core routing agent to configure LLM deployments. <ul><li>UI is available at **https://<CODESPACE_NAME>-4000.app.github.dev/ui**  </li><li>Credentials: admin, sk-password</li></ul> |
| 2    | Redis   | 6379 | Used as the caching layer for LLM calls.  |
| 3    | Postgres   | 5432 | Database layer to store LiteLLM and Langfuse metadata  |
| 4    | Langfuse   | 3001 | Tracing component used to keep track of LLM calls, latencies, and costs<ul><li>UI is available at **https://<CODESPACE_NAME>-3001.app.github.dev**</li><li>Credentials: admin@dep.com, password</li></ul>   |

## Basic Usage:

This repo has been configured to start with the LLM Gateway components listed above. Credentials for services such as LiteLLM and Langfuse are pre-set and can be accessed through the URLs listed in the components table above, or by using the PORTS tab (click on the globe icon near the forwarded address column on the corresponding port number to open in the browser).

![Codespace UI](images/codespace-ui.png)

#### LiteLLM Dashboard

You can access the LiteLLM dashboard by navigating to the URL `https://<CODESPACE_NAME>-4000.app.github.dev/ui` in your browser. The admin username is `admin` and the password is `sk-password` (which is the master password for litellm and is set with `LITELLM_MASTER_KEY` variable in `/opt/llm_gateway/.env`). 

![LiteLLM Dashboard](images/litellm-dashboard.png)

The LiteLLM dashboard allows you to configure models, virtual keys, and teams. One virtual key is pre-configured with this codespace. See the code in demo notebook under the 'Virtual Keys' section.

For more information on how to use virtual keys, refer to the [LiteLLM documentation](https://docs.litellm.ai/docs/proxy/virtual_keys). 

#### Langfuse Dashboard

This codespace is pre-configured with Langfuse, a tracing component that allows you to track and trace all your LLM calls, monitor requests and responses, and track cost and latencies of your LLM usage. You can access the Langfuse dashboard by navigating to the URL `https://<CODESPACE_NAME>-3001.app.github.dev` in your browser.  

![Langfuse Dashboard](images/langfuse-dashboard.png)

A langfuse project is pre-configured with this codespace and the login credentials to the project are 'admin@dep.com' and 'password'. LLM Gateway requires API keys (public key and secret key) to be set as environment variables. The API keys for the preconfigured project are set in the `.env` file at `/opt/llm_gateway/.env`.

`Note: Langfuse is pre-configured with a project and API keys. You can create a new project and set the API keys in the .env file to use Langfuse with your own project.`

### Customize models

The first step is to configure all the LLMs that you would like to route through the LLM Gateway. This can be done with a `model-config.yaml` file as shown below. 

This config file configures models from OpenAI, Bedrock, Anthropic and Ollama to be routed through the LLM Gateway. It also configures caching with Redis and tracing with Langfuse.

### Sample configuration for LiteLLM

```yaml filename="model-config.yaml"
model_list:
  - model_name: gpt-3.5-turbo
    litellm_params:
      model: openai/gpt-3.5-turbo
      api_key: os.environ/OPENAI_API_KEY
  - model_name: bedrock-llama2-13b 
    litellm_params: 
      model: bedrock/meta.llama2-13b-chat-v1 
      aws_region_name: us-east-1
  - model_name: gemini-pro
    litellm_params:
      model: vertex_ai/gemini-1.5-pro
      vertex_project: <GCP Project Name>
      vertex_location: "us-east1"
  - model_name: phi3 
    litellm_params:
      model: ollama/phi3 
      api_base: http://0.0.0.0:11434
      api_key: "dummy"
  - model_name: nomic-embed-text
    litellm_params:
      model: ollama/nomic-embed-text
      api_base: http://0.0.0.0:11434
      api_key: "dummy"
litellm_settings:
  success_callback: ["langfuse"] # Optional callback when Langfuse is enabled in feature, and required env variables are set in the environment
  failure_callback: ["langfuse"]
  langfuse_default_tags: ["cache_hit"]
  drop_params: True
  telemetry: False
  set_verbose: True
  cache: True          # set cache responses to True, litellm defaults to using a redis cache
  cache_params:
    type: "redis"
    ttl: 60            # Sets cache expiry to 1 minute
```

### Caching

A simple cache is configured in the default model config file that comes with this codespace. Semantic caching can be enabled by setting the `cache_params` in the model config file if supported embedding models are available. The version of Litellm that is configured currently only supports embedding models that can generate embedding vectors of size 1536. The following is a sample configuration for semantic caching using the `text-embedding-3-small` model from OpenAI.

```yaml
model_list:
  - model_name: gpt-3.5-turbo
    litellm_params:
      model: openai/gpt-3.5-turbo
      api_key: os.environ/OPENAI_API_KEY
  - model_name: text-embedding-3-small
    litellm_params:
      model: text-embedding-3-small
      api_key: os.environ/OPENAI_API_KEY
litellm_settings:
  cache: True
  cache_params:
    type: "redis-semantic"
    redis_semantic_cache_use_async: True
    similarity_threshold: 0.9                                    # similarity threshold for semantic cache
    redis_semantic_cache_embedding_model: text-embedding-3-small # set this to a model_name set in model_list
    ttl: 60                                                      # Sets cache expiry to 1 minute
    host: "localhost"                                            # Redis server
```

### Troubleshooting

Try the following steps if you encounter any issues while with LLM Gateway services in this codespace:

- Check the logs at `/opt/llm_gateway/logs/llm-gateway.log`
- Ensure the model config file is correctly configured
- Rebuild the codespace if any of the LLM Gateway components have not started properly.
- If the LiteLLM service is not running after the codespace starts or the service is unavailable in the PORTS tab, start the LLM Gateway with default configs by running the `postStart.sh` script manually by running `.devcontainer/postStart.sh` in the terminal

### References

This codespace LLM Gateway is built on top of the following open-source technologies:
- [LiteLLM](https://docs.litellm.ai/docs/)
- [Langfuse](https://langfuse.com/docs)
- [Redis-Stack](https://redis.io/blog/introducing-redis-stack/)
