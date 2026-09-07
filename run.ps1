$PROVIDER = 'ollama'

$MODEL_BASE_URL = 'http://localhost:11434'
$MODEL_AGENTS = 'qwen2.5-coder'

$LOG_LEVEL = 'INFO'

$SCRIPTS_PATH = "D:\scripts"
$REVIEWER_MAX_TOOL_ROUNDS = 0
$REVIEWER_MAX_SCHEMA_SCRIPTS = 0


python -m src.main --log-level ${LOG_LEVEL} --scripts-path ${SCRIPTS_PATH} --provider ${PROVIDER} --base-url ${MODEL_BASE_URL} --model-agent ${MODEL_AGENTS} --max-tool-rounds ${REVIEWER_MAX_TOOL_ROUNDS} --max-schema-scripts ${REVIEWER_MAX_SCHEMA_SCRIPTS}