from database import reset_db
from agent import SYSTEM_PROMPT, run_agent_turn


def start_chat():
    # 1. Automatic Database Reset on Launch
    reset_db()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("=" * 65)
    print("  Hi, I'm Paige from Bookly. What can I help you with today?")
    print("  Type 'exit' or 'quit' at any time to end the session.")
    print("=" * 65 + "\n")

    while True:
        try:
            raw_input = input("Customer: ").strip()

            # Handle empty inputs
            if not raw_input:
                continue

            # Graceful exit commands
            if raw_input.lower() in ["exit", "quit", "q"]:
                print("\nPaige: Thank you for visiting Bookly. Have a wonderful day!\n")
                break

            # Length and prompt-injection guardrails now live in agent.run_agent_turn,
            # so both interfaces (this CLI and the FastAPI storefront) get them for free.
            messages.append({"role": "user", "content": raw_input})
            agent_response, tools_called = run_agent_turn(messages)
            print(f"\nPaige: {agent_response}\n" + "-" * 65 + "\n")

        except KeyboardInterrupt:
            print("\n\nSession terminated by user.")
            break
        except Exception as e:
            print(f"\nAn error occurred while processing your request: {e}\n")


if __name__ == "__main__":
    start_chat()
