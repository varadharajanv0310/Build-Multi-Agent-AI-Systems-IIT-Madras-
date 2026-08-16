"""Evaluation against published expert decisions.

Every project in this hackathon can claim its system works. The distinguishing
claim here is a NUMBER, measured against ground truth nobody on this team
produced.

The ground truth is real and free: a published systematic review has already
done this job. Its reference list is the set of studies domain experts judged
relevant after full-text screening, and its abstract states whether the
included studies disagreed and what explained it. Replaying the same question
and diffing against that is an external check, not a self-graded exam.

The contrast worth stating: measuring a detector against defects you authored
yourself tells you about your test design, not your system.
"""

from faultline.eval.harness import BenchmarkCase, EvalResult, evaluate, find_review

__all__ = ["BenchmarkCase", "EvalResult", "evaluate", "find_review"]
