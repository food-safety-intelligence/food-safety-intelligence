from strands.models.bedrock import BedrockModel

def load_model() -> BedrockModel:
    return BedrockModel(
        model_id="us.amazon.nova-2-lite-v1:0",
        region_name="us-east-1",
        max_tokens=4096,
    )
