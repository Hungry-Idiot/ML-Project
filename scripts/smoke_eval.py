import json
from pathlib import Path
from datasets import load_dataset
from math_verify import parse, verify

OUT_PATH = Path("outputs/smoke_eval.jsonl")


def extract_boxed(text: str) -> str | None:
    """
    从文本中抽取最后一个 \\boxed{...} 的内容。
    支持 \\boxed{\\frac{1}{2}} 这种内部有花括号的情况。
    """
    key = "\\boxed{"
    start = text.rfind(key)
    if start == -1:
        return None

    i = start + len(key)
    depth = 1
    ans_chars = []

    while i < len(text):
        ch = text[i]

        if ch == "{":
            depth += 1
            ans_chars.append(ch)
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return "".join(ans_chars).strip()
            ans_chars.append(ch)
        else:
            ans_chars.append(ch)

        i += 1

    return None


def safe_verify(gold: str, pred_answer: str | None) -> bool:
    if pred_answer is None:
        return False

    gold_candidates = [
        gold,
        f"\\boxed{{{gold}}}",
        f"Final Answer: \\boxed{{{gold}}}",
    ]

    pred_candidates = [
        pred_answer,
        f"\\boxed{{{pred_answer}}}",
        f"Final Answer: \\boxed{{{pred_answer}}}",
    ]

    for g in gold_candidates:
        for p in pred_candidates:
            try:
                if verify(parse(g), parse(p)):
                    return True
            except Exception:
                pass

    return False


def main():
    ds = load_dataset(
        "json",
        data_files="data/MATH-500/test.jsonl",
        split="train"
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    correct = 0
    total = 10

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for i in range(total):
            ex = ds[i]
            problem = ex["problem"]
            gold = ex["answer"]

            fake_model_output = f"We solve the problem. Final Answer: \\boxed{{{gold}}}"

            pred_answer = extract_boxed(fake_model_output)
            is_correct = safe_verify(gold, pred_answer)
            correct += int(is_correct)

            if not is_correct:
                print("\n================ FAILED ================")
                print("id:", i)
                print("gold:", gold)
                print("pred_answer:", pred_answer)
                print("raw_output:", fake_model_output)

            record = {
                "id": i,
                "problem": problem,
                "gold": gold,
                "raw_output": fake_model_output,
                "pred_answer": pred_answer,
                "correct": is_correct,
            }

            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\nSaved to {OUT_PATH}")
    print(f"Accuracy: {correct}/{total} = {correct / total:.2%}")


if __name__ == "__main__":
    main()