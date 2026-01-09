#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./new_post.sh "My Post Title"
# If omitted, will use a default title.

title="${*:-New Post}"
bundle exec jekyll compose "$title" --post
