# Test Page: Claude GitHub App Review

This is a dummy page created to test the Claude GitHub App's PR review capability.

## Purpose

Validate that the `@claude` mention in PR comments triggers an automated code review
on this repository without requiring an Anthropic API key or GitHub Actions workflow.

## Sample Configuration

```python
REVIEW_SETTINGS = {
    "auto_review": True,
    "review_scope": "changed_files",
    "max_comment_length": 500,
    "ignore_patterns": ["*.lock", "*.min.js"],
}

def should_review_file(filename: str) -> bool:
    for pattern in REVIEW_SETTINGS["ignore_patterns"]:
        if filename.endswith(pattern.replace("*", "")):
            return False
    return True
```

## Cleanup

This file and its branch (`ty/test-claude-review`) are throwaway.
Delete the branch and close the PR once testing is complete.
