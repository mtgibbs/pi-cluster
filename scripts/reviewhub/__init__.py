"""review-hub — the reactive PR-evaluator service.

A GitHub App (one identity, installed on all repos) POSTs pull_request webhooks
to the in-cluster receiver, which dispatches to the applicable evaluators and
posts a Check Run + comment. Forge-agnostic core; GitHub today, GitLab/Gitea by
adding a forge + webhook parser. Evaluators are config, not credentials.
"""
