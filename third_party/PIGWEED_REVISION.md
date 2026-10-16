# Pigweed source pin

- Repository: `https://github.com/google/pigweed.git`
- Commit: `d6640a206bf18e78c3b965a03c71aabea67cf5b2`
- Retrieved as a shallow clone for STM32G474 Stage 5.1.

Do not update this dependency implicitly. Rebuild and rerun the Stage 5.1
device smoke test whenever the pinned revision changes.

The public repository records this checkout as a Git submodule. Initialize it
with `git submodule update --init --recursive` from the project root.
At publication, the local `pw_build/pigweed.cmake` status difference was
line-ending-only: `git diff --ignore-cr-at-eol` reported no source changes.
No semantic compatibility patch is required for this pinned checkout.
