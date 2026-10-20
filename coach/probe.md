# /coach probe

Runs the spaced-repetition probes that are due. Only execution-graded probe types from the active profiles count toward mastery. In those, the result comes from running something, not from your judgement of an answer.

## 1. What is due

Run `kg.py due` (add `--namespace <ns>` if the user asks for one stack). Nothing due: say so, with the next due date from `kg.py show`, and stop. Take at most five concepts per run, oldest due first. A concept with a recorded misconception goes before one without.

## 2. Build each probe

Use the probe types listed in the profile that owns the concept's namespace (`py.*` → python, `django.*` → django). `general.*` concepts use whichever active profile's type fits the material. If no execution-graded type fits the concept, say so and skip it: don't substitute a quiz.

Build from the user's own material, in this order:
1. A misconception they stated (from `kg.py show`): build the probe so that the misconception predicts the wrong result.
2. Code they wrote: the files and commits in the concept's evidence refs, as it is on HEAD now.
3. Code elsewhere in this repo that uses the concept.

Write the probe card to `.coach/logs/probes/<date>-<concept>.md` before showing it:
- **Setup.** The worktree, scratch test file or mutant, under `.coach/logs/probes/` or a `git worktree` in a temp dir. Never in the user's working tree.
- **Prompt.** What the user must predict or produce.
- **Grading command.** The exact command.
- **Pass criterion.** What output makes it a pass, written down before the user answers.

Show the user the prompt only. Not the grading command if it gives the answer away, and not the expected result.

## 3. Grade

1. Get the user's prediction or code.
2. Run the grading command.
3. Show the output next to their prediction.
4. Record `kg.py record <concept> --kind probe-pass|probe-fail --ref "repo=<repo> probe=<type> file=<card path>" --note "<prediction> vs <result>"`.

Use `--unverified` on a draft profile, or if grading depended on a gate that isn't available.

A verbal explanation without the executed check is not a probe pass. If that is all the user gives, record it as `prereq-pass` or `prereq-fail`, which never moves mastery.

## 4. After a fail

Run the teaching loop (SKILL.md), with example code faded to the concept's current mastery. If the user states the reason they expected their answer, record it verbatim as a misconception. Don't re-probe the same concept in the same run; the box reset schedules it for tomorrow.

## 5. Clean up

Remove probe worktrees. Keep the cards (`.coach/logs/` is gitignored). Finish with `kg.py validate` and `kg.py commit -m "probe: <n> run, <pass>/<n> passed"`.
