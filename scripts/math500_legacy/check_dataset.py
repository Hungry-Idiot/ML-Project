from datasets import load_dataset

def main():
    ds = load_dataset(
        "json",
        data_files="data/MATH-500/test.jsonl",
        split="train"
    )
    
    print(ds)
    print("Number of examples:", len(ds))
    print("Columns:", ds.column_names)

    ex = ds[0]
    print("\n=== Example ===")
    for k, v in ex.items():
        print(f"\n[{k}]")
        print(v)

if __name__ == "__main__":
    main()