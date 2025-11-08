import tiktoken
import sys

def count_tokens_in_file(file_path: str, model: str = "sonnet4.5") -> int:
    """Count tokens in a text file using OpenAI's tiktoken tokenizer."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        print(f"❌ File not found: {file_path}")
        return 0

    encoding = tiktoken.encoding_for_model(model)
    tokens = encoding.encode(text)
    token_count = len(tokens)

    print(f"📄 File: {file_path}")
    print(f"🧠 Model: {model}")
    print(f"🔢 Token count: {token_count:,}")

    return token_count


if __name__ == "__main__":
    # Usage: python3 token_counter.py result.txt
    if len(sys.argv) < 2:
        print("Usage: python3 token_counter.py <file_path> [model]")
    else:
        file_path = sys.argv[1]
        model = sys.argv[2] if len(sys.argv) > 2 else "gpt-4o-mini"
        count_tokens_in_file(file_path, model)
