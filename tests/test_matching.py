from loot_player.matching import parse_generic


def test_generic_strips_extension():
    assert parse_generic("Hello World.mkv") == {"title": "Hello World"}


def test_generic_handles_multi_dot_filename():
    assert parse_generic("foo.bar.baz.mp4") == {"title": "foo.bar.baz"}


def test_generic_handles_no_extension():
    assert parse_generic("README") == {"title": "README"}


from loot_player.matching import parse_movie


def test_movie_paren_year():
    out = parse_movie("The Matrix (1999).mkv")
    assert out["title"] == "The Matrix"
    assert out["year"] == 1999


def test_movie_dot_year_scene_release():
    out = parse_movie("The.Matrix.1999.1080p.BluRay.x264.mkv")
    assert out["title"] == "The Matrix"
    assert out["year"] == 1999


def test_movie_bracket_year():
    out = parse_movie("Inception [2010].mp4")
    assert out["title"] == "Inception"
    assert out["year"] == 2010


def test_movie_year_in_title_does_not_confuse():
    out = parse_movie("2001 A Space Odyssey (1968).mkv")
    assert out["year"] == 1968
    assert "2001" in out["title"]


def test_movie_no_year_fallback():
    out = parse_movie("Some Random Movie.mkv")
    assert out["title"] == "Some Random Movie"
    assert out["year"] is None


def test_movie_implausible_year_ignored():
    out = parse_movie("Old Footage 1850.mkv")
    assert out["year"] is None


from loot_player.matching import parse_tv


def test_tv_sxxeyy_pattern():
    out = parse_tv("Breaking Bad - S01E03 - Pilot.mkv", parent_dir="/tv")
    assert out["series"] == "Breaking Bad"
    assert out["season"] == 1
    assert out["episode"] == 3


def test_tv_dot_separated_lower():
    out = parse_tv("breaking.bad.s05e14.felina.mkv", parent_dir="/tv")
    assert out["season"] == 5
    assert out["episode"] == 14


def test_tv_one_x_pattern():
    out = parse_tv("Severance 1x07.mp4", parent_dir="/tv")
    assert out["series"] == "Severance"
    assert out["season"] == 1
    assert out["episode"] == 7


def test_tv_folder_season_episode_in_filename():
    out = parse_tv("01 - Pilot.mkv", parent_dir="/tv/Breaking Bad/Season 1")
    assert out["series"] == "Breaking Bad"
    assert out["season"] == 1
    assert out["episode"] == 1


def test_tv_folder_season_s0n():
    out = parse_tv("03 - The Cat in the Bag.mkv",
                   parent_dir="/tv/Breaking Bad/S02")
    assert out["season"] == 2
    assert out["episode"] == 3


def test_tv_unsorted_fallback():
    out = parse_tv("random episode title.mkv",
                   parent_dir="/tv/Some Show")
    assert out["series"] == "Some Show"
    assert out["season"] is None
    assert out["episode"] is None


def test_tv_sxxeyy_at_start_uses_folder_for_series():
    # Filename starts with SxxEyy; series comes from the folder.
    out = parse_tv("S01E01.mkv", parent_dir="/tv/Breaking Bad")
    assert out["series"] == "Breaking Bad"
    assert out["season"] == 1
    assert out["episode"] == 1


def test_tv_one_x_at_start_uses_folder_for_series():
    out = parse_tv("1x07 Foo.mkv", parent_dir="/tv/Severance")
    assert out["series"] == "Severance"
    assert out["season"] == 1
    assert out["episode"] == 7


from loot_player.matching import parse_music


def test_music_three_level_layout():
    out = parse_music(
        filename="01 - Black Dog.mp3",
        parent_dir="/music/Led Zeppelin/IV",
    )
    assert out["artist"] == "Led Zeppelin"
    assert out["album"] == "IV"
    assert out["track"] == 1
    assert out["title"] == "Black Dog"


def test_music_two_level_no_artist():
    out = parse_music(
        filename="03 - Track.mp3",
        parent_dir="/music/Greatest Hits",
    )
    assert out["artist"] is None
    assert out["album"] == "Greatest Hits"
    assert out["track"] == 3


def test_music_flat_no_artist_no_album():
    out = parse_music(filename="random.mp3", parent_dir="/music")
    assert out["artist"] is None
    assert out["album"] is None
    assert out["title"] == "random"


from loot_player.matching import parse


def test_dispatch_movies():
    out = parse("movies", "Arrival (2016).mkv", "/movies")
    assert out["year"] == 2016


def test_dispatch_unknown_type_falls_to_generic():
    out = parse("nonsense", "x.mp4", "/foo")
    assert out == {"title": "x"}
