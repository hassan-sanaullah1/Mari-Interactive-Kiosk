#!/bin/sh
# Refuses a push from a branch whose name breaks the rule in AGENTS.md (Git section).
# Runs as the pre-push hook that `make setup` installs (.pre-commit-config.yaml), so a
# badly named branch is caught before its pull request exists.
#
# BRANCH overrides the current branch, for trying a name without creating it:
#   BRANCH=fix/urdu-status-gender scripts/check_branch_name.sh

branch="${BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"

# Long-lived branches, release branches, Dependabot's own, and a detached HEAD.
case "$branch" in
  develop | staging | main | master | dependabot/* | HEAD) exit 0 ;;
esac

if printf '%s\n' "$branch" | grep -Eq \
  '^(feature|fix|hotfix|chore|docs|refactor)/[a-z0-9]+(-[a-z0-9]+)*$|^release/v[0-9]+\.[0-9]+$'; then
  exit 0
fi

cat >&2 <<EOF
Branch name "$branch" does not follow <type>/<short-description>.
  Types: feature, fix, hotfix, chore, docs, refactor. Lowercase words joined by hyphens.
  Example: fix/urdu-status-gender
Rename it with: git branch -m <new-name>
EOF
exit 1
