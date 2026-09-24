import re
from database import reset_db
from agent import SYSTEM_PROMPT, run_agent_turn

# Heuristic jailbreak and prompt-injection patterns
INJECTION_PATTERNS = [
    r"ignore\s+(all|any|previous|prior)\s+instructions",
    r"disregard\s+(all|any|previous|prior)",
    r"system\s*prompt",
    r"you\s+are\s+now\s+(a|an|dan)",
    r"developer\s+mode",
    r"jailbreak",
    r"act\s+as\s+",
    r"pretend\s+to\s+be\s+"
]

MAX_INPUT_LENGTH = 300  # Avoid large payloads or token exhaustion attacks


def is_suspicious(text: str) -> bool:
    """Detects prompt injection signatures before invoking the LLM."""
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in INJECTION_PATTERNS)


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

            # 1. Payload Length Guardrail
            if len(raw_input) > MAX_INPUT_LENGTH:
                print(
                    "\nPaige: Your message is too long for our automated system. "
                    "Please provide a shorter message with your Order ID, email, or inquiry.\n"
                    + "-" * 65 + "\n"
                )
                continue

            # 2. Heuristic Prompt-Injection Guardrail
            if is_suspicious(raw_input):
                print(
                    "\nPaige: I am only authorized to assist with Bookly orders, returns, "
                    "and book catalog inquiries. How can I help you with your order today?\n"
                    + "-" * 65 + "\n"
                )
                continue

            # 3. Process Safe Turn
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