import pandas as pd
from src.tonality_classifier import classify_tonality

def _df(title: str, body: str = '', **flags) -> pd.DataFrame:
    base = {
        'Android Message Title (Android, Web), Title (iOS)': title,
        'Android Message (Android, Web), Subtitle (iOS)': body,
        'is_forced_genz': False,
        'is_corporate_jargon': False,
        'has_specific_number': False,
        'has_cultural_reference': False,
        'has_personalisation': False,
        'has_exclamation': False,
    }
    base.update(flags)
    return pd.DataFrame([base])

def test_forced_genz_labelled():
    df = classify_tonality(_df('bestie this deal', is_forced_genz=True))
    assert df.iloc[0]['tonality'] == "DON'T: Forced Gen Z"
    assert df.iloc[0]['tonality_parent'] == "DON'T"
    assert df.iloc[0]['brand_compliant'] == False

def test_corporate_jargon_labelled():
    df = classify_tonality(_df('Eligible unredeemed points', is_corporate_jargon=True))
    assert df.iloc[0]['tonality'] == "DON'T: Corporate Jargon"
    assert df.iloc[0]['brand_compliant'] == False

def test_condescending_labelled():
    df = classify_tonality(_df("You haven't tried POP UPI yet"))
    assert df.iloc[0]['tonality'] == "DON'T: Condescending"

def test_lecture_y_labelled():
    body = 'Please note that you should complete your KYC before you can use this offer as per our terms and conditions today'
    df = classify_tonality(_df('Important information', body=body))
    assert df.iloc[0]['tonality'] == "DON'T: Lecture-y"

def test_vague_labelled():
    # "check this out" is in VAGUE_PHRASES but NOT in CLICHE_PHRASES
    df = classify_tonality(_df("Check this out now"))
    assert df.iloc[0]['tonality'] == "DON'T: Vague"

def test_cliche_labelled():
    df = classify_tonality(_df("Exclusive offer just for you"))
    assert df.iloc[0]['tonality'] == "DON'T: Cliche"

def test_something_special_is_cliche_not_vague():
    """'Something special awaits' matches both Cliche and Vague — Cliche wins per priority."""
    df = classify_tonality(_df("Something special awaits"))
    assert df.iloc[0]['tonality'] == "DON'T: Cliche"

def test_value_aware_labelled():
    df = classify_tonality(_df('Get cashback', has_specific_number=True))
    assert df.iloc[0]['tonality'] == 'DO: Smart — Value-aware'
    assert df.iloc[0]['tonality_parent'] == 'DO'
    assert df.iloc[0]['brand_compliant'] == True

def test_unique_labelled():
    df = classify_tonality(_df('"Why so serious?" Smile and save'))
    assert df.iloc[0]['tonality'] == 'DO: Smart — Unique'

def test_youthful_labelled():
    df = classify_tonality(_df('IPL prediction special', has_cultural_reference=True))
    assert df.iloc[0]['tonality'] == 'DO: Relatable — Youthful'

def test_friendly_labelled():
    df = classify_tonality(_df('We gotchu! Rewards are here', has_personalisation=True))
    assert df.iloc[0]['tonality'] == 'DO: Relatable — Friendly'

def test_simple_is_fallback_do():
    df = classify_tonality(_df('Pay with POP UPI now'))
    assert df.iloc[0]['tonality'] == 'DO: Smart — Simple'

def test_forced_genz_takes_priority_over_value_aware():
    df = classify_tonality(_df('bestie grab rewards', is_forced_genz=True, has_specific_number=True))
    assert df.iloc[0]['tonality'] == "DON'T: Forced Gen Z"

def test_tonality_subtype_derived():
    df = classify_tonality(_df('Get cashback now', has_specific_number=True))
    assert df.iloc[0]['tonality_subtype'] == 'Smart — Value-aware'

def test_brand_compliant_true_for_do():
    df = classify_tonality(_df('Pay now and earn rewards'))
    assert df.iloc[0]['brand_compliant'] == True

def test_brand_compliant_false_for_dont():
    df = classify_tonality(_df('bestie deal', is_forced_genz=True))
    assert df.iloc[0]['brand_compliant'] == False
