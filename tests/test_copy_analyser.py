import pandas as pd
from src.copy_analyser import analyse_copy

def _df(title: str, body: str = '', image: str = '') -> pd.DataFrame:
    return pd.DataFrame([{
        'Android Message Title (Android, Web), Title (iOS)': title,
        'Android Message (Android, Web), Subtitle (iOS)': body,
        'Android Rich Content Image URL': image,
    }])

def test_emoji_detected():
    df = analyse_copy(_df('Win ₹50 POPcoins today 🎉'))
    assert df.iloc[0]['has_emoji'] == True
    assert df.iloc[0]['emoji_count'] == 1

def test_no_emoji():
    df = analyse_copy(_df('Win 50 POPcoins today'))
    assert df.iloc[0]['has_emoji'] == False
    assert df.iloc[0]['emoji_count'] == 0

def test_emoji_count_bucket_zero():
    df = analyse_copy(_df('No emojis here'))
    assert df.iloc[0]['emoji_count_bucket'] == '0'

def test_emoji_count_bucket_one():
    df = analyse_copy(_df('Hello 🎉'))
    assert df.iloc[0]['emoji_count_bucket'] == '1'

def test_emoji_count_bucket_two_plus():
    df = analyse_copy(_df('Hello 🎉 World 🚀'))
    assert df.iloc[0]['emoji_count_bucket'] == '2+'

def test_emoji_position_start():
    df = analyse_copy(_df('🎉 Win today'))
    assert df.iloc[0]['emoji_position'] == 'Start'

def test_emoji_position_end():
    df = analyse_copy(_df('Win today 🎉'))
    assert df.iloc[0]['emoji_position'] == 'End'

def test_emoji_position_none():
    df = analyse_copy(_df('Win today'))
    assert df.iloc[0]['emoji_position'] == 'None'

def test_title_char_length():
    df = analyse_copy(_df('Win today'))
    assert df.iloc[0]['title_char_length'] == 9

def test_title_word_count():
    df = analyse_copy(_df('Win fifty POPcoins today'))
    assert df.iloc[0]['title_word_count'] == 4

def test_title_length_bucket_short():
    df = analyse_copy(_df('Win now'))
    assert df.iloc[0]['title_length_bucket'] == 'Short'

def test_title_length_bucket_medium():
    df = analyse_copy(_df('Win fifty POPcoins on your next UPI transaction now'))
    assert df.iloc[0]['title_length_bucket'] == 'Medium'

def test_title_length_bucket_long():
    df = analyse_copy(_df('Win fifty POPcoins on your next UPI transaction now and get more'))
    assert df.iloc[0]['title_length_bucket'] == 'Long'

def test_has_personalisation_you():
    df = analyse_copy(_df('Your rewards are waiting'))
    assert df.iloc[0]['has_personalisation'] == True

def test_has_personalisation_false():
    df = analyse_copy(_df('Rewards are waiting'))
    assert df.iloc[0]['has_personalisation'] == False

def test_has_specific_number_rupee():
    df = analyse_copy(_df('Get cashback', body='Earn ₹50 now'))
    assert df.iloc[0]['has_specific_number'] == True

def test_has_specific_number_popcoins():
    df = analyse_copy(_df('Earn 100 POPcoins'))
    assert df.iloc[0]['has_specific_number'] == True

def test_has_specific_number_percent():
    df = analyse_copy(_df('Save 20% today'))
    assert df.iloc[0]['has_specific_number'] == True

def test_has_specific_number_false():
    df = analyse_copy(_df('Earn big rewards'))
    assert df.iloc[0]['has_specific_number'] == False

def test_has_action_verb():
    df = analyse_copy(_df('Claim your reward now'))
    assert df.iloc[0]['has_action_verb'] == True

def test_has_exclamation():
    df = analyse_copy(_df('Win today!'))
    assert df.iloc[0]['has_exclamation'] == True

def test_has_question_mark():
    df = analyse_copy(_df('Ready to win?'))
    assert df.iloc[0]['has_question_mark'] == True

def test_has_fomo_signal():
    df = analyse_copy(_df('Last chance to win'))
    assert df.iloc[0]['has_fomo_signal'] == True

def test_has_cultural_reference_ipl():
    df = analyse_copy(_df('IPL prediction special'))
    assert df.iloc[0]['has_cultural_reference'] == True

def test_has_rich_media_true():
    df = analyse_copy(_df('title', image='https://cdn.popclub.co/img.jpg'))
    assert df.iloc[0]['has_rich_media'] == True

def test_has_rich_media_false():
    df = analyse_copy(_df('title', image=''))
    assert df.iloc[0]['has_rich_media'] == False

def test_is_forced_genz():
    df = analyse_copy(_df('bestie this deal is here'))
    assert df.iloc[0]['is_forced_genz'] == True

def test_is_corporate_jargon():
    df = analyse_copy(_df('Redeem your eligible POPcoins'))
    assert df.iloc[0]['is_corporate_jargon'] == True

def test_action_verb_no_false_positive_on_forget():
    """'get' in ACTION_VERBS must not match inside 'forget'."""
    df = analyse_copy(_df('I forget sometimes'))
    assert df.iloc[0]['has_action_verb'] == False

def test_corporate_jargon_no_false_positive_on_available():
    """'avail' in CORPORATE_JARGON must not match inside 'available'."""
    df = analyse_copy(_df('Offer available for you'))
    assert df.iloc[0]['is_corporate_jargon'] == False

def test_forced_genz_no_false_positive_on_family():
    """'fam' in FORCED_GENZ must not match inside 'family'."""
    df = analyse_copy(_df('Share with family'))
    assert df.iloc[0]['is_forced_genz'] == False

def test_fomo_no_false_positive_on_unlimited():
    """'limited' in FOMO_WORDS must not match inside 'unlimited'."""
    df = analyse_copy(_df('Unlimited cashback every day'))
    assert df.iloc[0]['has_fomo_signal'] == False
