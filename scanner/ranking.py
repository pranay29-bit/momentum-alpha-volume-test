import numpy as np


# ---------------------------------------------------
# Trend Template Score (30)
# ---------------------------------------------------
def trend_score(row):
    score = 0

    if row["Close"] > row["SMA50"]:
        score += 4

    if row["Close"] > row["SMA150"]:
        score += 4

    if row["Close"] > row["SMA200"]:
        score += 4

    if row["SMA50"] > row["SMA150"]:
        score += 4

    if row["SMA150"] > row["SMA200"]:
        score += 4

    if row.get("MA200_Rising", False):
        score += 5

    if row["Close"] >= row["52W Low"] * 1.30:
        score += 3

    if row["Close"] >= row["52W High"] * 0.75:
        score += 2

    return score


# ---------------------------------------------------
# Relative Strength Score (20)
# ---------------------------------------------------
def rs_score(rs):

    if rs >= 95:
        return 20
    elif rs >= 90:
        return 18
    elif rs >= 85:
        return 16
    elif rs >= 80:
        return 14
    elif rs >= 75:
        return 12
    elif rs >= 70:
        return 10
    elif rs >= 60:
        return 6
    else:
        return 0


# ---------------------------------------------------
# Moving Average Quality (15)
# ---------------------------------------------------
def ma_quality(row):

    score = 0

    if row["SMA50 Slope"] > 0:
        score += 5

    if row["SMA150 Slope"] > 0:
        score += 4

    if row["SMA200 Slope"] > 0:
        score += 4

    spread = (row["SMA50"] - row["SMA200"]) / row["SMA200"]

    if spread > 0.10:
        score += 2

    return score


# ---------------------------------------------------
# Volume Quality (15)
# ---------------------------------------------------
def volume_score(row):

    score = 0

    if row["Volume"] > row["Volume20"] * 1.5:
        score += 5

    if row.get("Accumulation Days", 0) >= 3:
        score += 5

    if row.get("Dry Volume", False):
        score += 5

    return score


# ---------------------------------------------------
# Momentum Score (10)
# ---------------------------------------------------
def momentum_score(row):

    score = 0

    if row["1M Return"] > 10:
        score += 3

    if row["3M Return"] > 20:
        score += 4

    if row["6M Return"] > 40:
        score += 3

    return score


# ---------------------------------------------------
# Liquidity (5)
# ---------------------------------------------------
def liquidity_score(row):

    tv = row["Traded Value"]

    if tv > 1000:
        return 5

    if tv > 500:
        return 4

    if tv > 250:
        return 3

    if tv > 100:
        return 2

    return 0


# ---------------------------------------------------
# Grade
# ---------------------------------------------------
def grade(score):

    if score >= 95:
        return "A+"

    if score >= 90:
        return "A"

    if score >= 85:
        return "A-"

    if score >= 80:
        return "B+"

    if score >= 75:
        return "B"

    return "C"


# ---------------------------------------------------
# Master Ranking
# ---------------------------------------------------
def calculate_minervini_score(df):

    trend = []
    rs = []
    ma = []
    volume = []
    momentum = []
    liquidity = []
    total = []
    grades = []

    for _, row in df.iterrows():

        t = trend_score(row)
        r = rs_score(row["RS Percentile"])
        m = ma_quality(row)
        v = volume_score(row)
        mo = momentum_score(row)
        l = liquidity_score(row)

        s = t + r + m + v + mo + l

        trend.append(t)
        rs.append(r)
        ma.append(m)
        volume.append(v)
        momentum.append(mo)
        liquidity.append(l)
        total.append(s)
        grades.append(grade(s))

    df["Trend Score"] = trend
    df["RS Score"] = rs
    df["MA Score"] = ma
    df["Volume Score"] = volume
    df["Momentum Score"] = momentum
    df["Liquidity Score"] = liquidity

    df["Minervini Score"] = total
    df["Grade"] = grades

    return df.sort_values("Minervini Score", ascending=False)
