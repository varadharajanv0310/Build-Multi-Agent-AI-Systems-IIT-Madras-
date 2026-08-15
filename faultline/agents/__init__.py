"""The council.

Every agent takes a Role and returns a typed record. None of them knows which
model it is running on — that binding lives in config.ROSTER, which is what
lets opposed roles sit on genuinely different training lineages.
"""
