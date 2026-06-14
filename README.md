# Math-DeLM Course Project

This project explores a lightweight DeLM-style framework for mathematical reasoning on MATH-500.

## Current Progress

Day 1:
- Loaded local MATH-500 JSONL dataset.
- Implemented answer extraction from \boxed{}.
- Implemented automatic answer verification with math-verify.
- Ran Single-CoT baseline on 20 examples.

Current Single-CoT-20 result:
- Total: 20
- Correct: 18
- Accuracy: 90.00%
- Parse fail: 2
- Parse success: 90.00%

## Data

The dataset file should be placed locally at:

data/MATH-500/test.jsonl

The data directory is ignored by Git and is not uploaded.

## Environment

Create environment:

conda create -n mathdelm python=3.11 -y
conda activate mathdelm

Install dependencies:

pip install -r requirements.txt