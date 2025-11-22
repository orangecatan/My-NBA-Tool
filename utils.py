import pandas as pd
from datetime import datetime, timedelta
from nba_api.stats.endpoints import leaguegamefinder, leaguedashplayerstats, leaguedashteamstats
from nba_api.stats.static import teams
import time
from requests.exceptions import ReadTimeout, ConnectionError, RequestException

# Constants
CACHE_DURATION = 3600 # 1 hour

def retry_api_call(func, retries=5, delay=5):
    """
    Wraps an API call with retry logic.
    """
    for i in range(retries):
        try:
            return func()
        except (ReadTimeout, ConnectionError, RequestException) as e:
            print(f"  ⚠️ API Error (Attempt {i+1}/{retries}): {e}")
            if i < retries - 1:
                sleep_time = delay * (i + 1)
                print(f"  ⏳ Retrying in {sleep_time}s...")
                time.sleep(sleep_time)
            else:
                print("  ❌ Max retries reached.")
                raise e

def get_schedule(start_date, end_date, season='2025-26'):
    """
    Fetches schedule between start_date and end_date.
    Returns a DataFrame with columns: [TEAM_ID, TEAM_ABBREVIATION, GAME_DATE, MATCHUP]
    """
    start_str = start_date.strftime('%m/%d/%Y')
    end_str = end_date.strftime('%m/%d/%Y')
    
    def fetch_schedule():
        return leaguegamefinder.LeagueGameFinder(
            league_id_nullable='00',
            date_from_nullable=start_str,
            date_to_nullable=end_str,
            season_nullable=season, # Explicitly request the season
            season_type_nullable='Regular Season',
            timeout=60 # Increase timeout if supported, otherwise ignored
        )

    try:
        game_finder = retry_api_call(fetch_schedule)
        games = game_finder.get_data_frames()[0]
    except Exception:
        return pd.DataFrame()
    
    if games.empty:
        return pd.DataFrame()

    # Filter and clean
    games = games[['TEAM_ID', 'TEAM_ABBREVIATION', 'GAME_DATE', 'MATCHUP']]
    games['GAME_DATE'] = pd.to_datetime(games['GAME_DATE']).dt.date
    
    # Ensure TEAM_ID is int for merging
    games['TEAM_ID'] = games['TEAM_ID'].astype(int)
    
    return games

def get_player_stats_multi_period(season='2025-26'):
    """
    Fetches stats for:
    1. Season (e.g. 2025-26)
    2. Last 7 Days
    3. Last 14 Days
    
    Returns a dictionary of DataFrames: {'Season': df, 'L7': df, 'L14': df}
    """
    
    # Helper to fetch stats with optional date filter
    def fetch_stats(date_from=None):
        date_from_str = date_from.strftime('%m/%d/%Y') if date_from else ''
        
        def fetch():
            return leaguedashplayerstats.LeagueDashPlayerStats(
                per_mode_detailed='PerGame',
                season=season, # Explicitly request the season
                season_type_all_star='Regular Season',
                date_from_nullable=date_from_str,
                timeout=60
            )
            
        try:
            stats = retry_api_call(fetch)
            df = stats.get_data_frames()[0]
        except Exception:
            return pd.DataFrame() # Return empty on failure
        
        # Select key columns
        cols = [
            'PLAYER_ID', 'PLAYER_NAME', 'TEAM_ID', 'TEAM_ABBREVIATION', 'GP',
            'MIN', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'FG_PCT', 'FT_PCT', 'FG3M'
        ]
        # Ensure columns exist
        existing_cols = [c for c in cols if c in df.columns]
        df = df[existing_cols]
        df['TEAM_ID'] = df['TEAM_ID'].astype(int)
        return df

    print("  Fetching Season Stats...")
    df_season = fetch_stats()
    
    # Calculate dates
    today = datetime.now().date()
    
    # Check if we need Time Travel for L7/L14
    # If df_season is empty or very small, we might be in off-season or wrong date.
    # But assuming Season stats work (as verified before).
    
    # L7
    d7 = today - timedelta(days=7)
    print(f"  Fetching L7 Stats (from {d7})...")
    df_l7 = fetch_stats(d7)
    
    # L14
    d14 = today - timedelta(days=14)
    print(f"  Fetching L14 Stats (from {d14})...")
    df_l14 = fetch_stats(d14)
    
    return {
        'Season': df_season,
        'L7': df_l7,
        'L14': df_l14
    }

def get_team_defensive_ratings(season='2025-26'):
    """
    Fetches team defensive ratings.
    Returns a dict: {TeamAbbr: {'Rank': int, 'DefRtg': float}}
    """
    # Use 'Advanced' to get DEF_RATING
    def fetch_def():
        return leaguedashteamstats.LeagueDashTeamStats(
            per_mode_detailed='PerGame',
            season=season, # Explicitly request the season
            season_type_all_star='Regular Season',
            measure_type_detailed_defense='Advanced',
            timeout=60
        )
        
    try:
        stats_adv = retry_api_call(fetch_def)
        df = stats_adv.get_data_frames()[0]
    except Exception:
        return {} # Return empty dict on failure
    
    # Create ID -> Abbr map
    nba_teams = teams.get_teams()
    id_to_abbr = {team['id']: team['abbreviation'] for team in nba_teams}
    
    # Sort by DEF_RATING
    if 'DEF_RATING' in df.columns:
        df = df.sort_values('DEF_RATING', ascending=True) # 1=Best
    else:
        # Fallback: Sort by W_PCT (Better teams are usually harder)
        df = df.sort_values('W_PCT', ascending=False)
        
    df['DEF_RANK'] = range(1, len(df) + 1)
    
    # Create map: ABBR -> Rank
    def_map = {}
    for _, row in df.iterrows():
        tid = row['TEAM_ID']
        abbr = id_to_abbr.get(tid, 'UNK')
        
        def_map[abbr] = {
            'Rank': row['DEF_RANK'],
            'DefRtg': row.get('DEF_RATING', 0.0)
        }
        
    return def_map

def get_color_for_rank(rank):
    """
    Returns a hex color based on rank (1-30).
    Rank 1 (Best Def) -> Red (Bad for Fantasy)
    Rank 30 (Worst Def) -> Green (Good for Fantasy)
    """
    # 5-step scale
    if rank <= 6:
        return "#ffcccc" # Red (Hard)
    elif rank <= 12:
        return "#ffe5cc" # Orange
    elif rank <= 18:
        return "#ffffcc" # Yellow
    elif rank <= 24:
        return "#e5ffcc" # Light Green
    else:
        return "#ccffcc" # Green (Easy)
