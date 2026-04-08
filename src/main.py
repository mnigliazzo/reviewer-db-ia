import argparse
import logging
import sys
from langchain.agents import create_agent
from .skill_middleware import SkillMiddleware
from langchain_ollama import ChatOllama

logger = logging.getLogger(__name__)



def main():
    parser = argparse.ArgumentParser(description="CI SQL Reviewer powered by AI")
    parser.add_argument("--scripts-path", type=str, required=True, help="Path to the SQL scripts to review")
    parser.add_argument("--ollama-url", type=str, required=True, help="Ollama API URL")
    parser.add_argument("--model-agent", type=str, required=True, help="AI Model Agent name")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")

    args = parser.parse_args()
    
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


    # 2. Inicializar Modelo LLM (NO un agent ReAct - el modelo de 3B no soporta tool-calling autónomo)
    # Las herramientas se usan programáticamente en _fetch_context(), no por el LLM.
    logger.info(f"🤖 Inicializando modelo LLM para análisis de SQL")
    
    model =  ChatOllama(
        base_url=args.ollama_url,
        model=args.model_agent
    )
    
    agent = create_agent(
        model,
        system_prompt=(
            "You are a SQL query assistant that helps users "
            "write queries against business databases."
        ),
        middleware=[SkillMiddleware()]
    )
    
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Write a SQL query to find all customers "
                        "who made orders over $1000 in the last month"
                    ),
                }
            ]
        }
    )

    # Print the conversation
    for message in result["messages"]:
        logger.info(f"{message.type}: {message.content}")

    if result.get("error"):
        logger.error(f"❌ La revisión falló: {result['error']}")
        sys.exit(1)

if __name__ == "__main__":
    main()
