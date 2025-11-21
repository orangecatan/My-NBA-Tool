import pandas as pd
from datetime import datetime, timedelta
from nba_api.stats.endpoints import leaguegamefinder, leaguedashplayerstats, leaguedashteamstats
from nba_api.stats.static import teams
import time

# Constants
CACHE_DURATION = 3600 # 1 hour

def get_schedule(start_date, end_date):
    """
    Fetches schedule between start_date and end_date.
    Returns a DataFrame with columns: [TEAM_ID, TEAM_ABBREVIATION, GAME_DATE, MATCHUP]
    """
    start_str = start_date.strftime('%m/%d/%Y')
    end_str = end_date.strftime('%m/%d/%Y')
    
    game_finder = leaguegamefinder.LeagueGameFinder(
        league_id_nullable='00',
        date_from_nullable=start_str,
        date_to_nullable=end_str,
        season_type_nullable='Regular Season'
    )
    games = game_finder.get_data_frames()[0]
    
    if games.empty:
        return pd.DataFrame()

    # Filter and clean
    games = games[['TEAM_ID', 'TEAM_ABBREVIATION', 'GAME_DATE', 'MATCHUP']]
    games['GAME_DATE'] = pd.to_datetime(games['GAME_DATE']).dt.date
    
    # Ensure TEAM_ID is int for merging
    games['TEAM_ID'] = games['TEAM_ID'].astype(int)
    
    return games

def get_player_stats_multi_period():
    """
    Fetches stats for:
    1. Season (2024-25)
    2. Last 7 Days
    3. Last 14 Days
    
    Returns a dictionary of DataFrames: {'Season': df, 'L7': df, 'L14': df}
    """
    
    # Helper to fetch stats with optional date filter
    def fetch_stats(date_from=None):
        date_from_str = date_from.strftime('%m/%d/%Y') if date_from else ''
        
        # If we are in "Time Travel" mode (2025 system time but 2024 season),
        # we might need to adjust the date_from query.
        # But for simplicity, let's try standard query first.
        
        stats = leaguedashplayerstats.LeagueDashPlayerStats(
            per_mode_detailed='PerGame',
            season_type_all_star='Regular Season',
            date_from_nullable=date_from_str
        )
        df = stats.get_data_frames()[0]
        
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
    
    # Fallback: If L7/L14 are empty (because of 2025 date), try 2024 dates
    if df_l7.empty and not df_season.empty:
        print("  ⚠️ L7 empty. Trying 2024 dates for L7/L14...")
        today_2024 = today.replace(year=today.year - 1)
        d7_2024 = today_2024 - timedelta(days=7)
        d14_2024 = today_2024 - timedelta(days=14)
        
        df_l7 = fetch_stats(d7_2024)
        df_l14 = fetch_stats(d14_2024)

    return {
        'Season': df_season,
        'L7': df_l7,
        'L14': df_l14
    }

def get_team_defensive_ratings():
    """
    Fetches team defensive ratings.
    Returns a dict: {TeamAbbr: {'Rank': int, 'DefRtg': float}}
    """
    # Use 'Advanced' to get DEF_RATING
    stats_adv = leaguedashteamstats.LeagueDashTeamStats(
        per_mode_detailed='PerGame',
        season_type_all_star='Regular Season',
        measure_type_detailed_defense='Advanced'
    )
    df = stats_adv.get_data_frames()[0]
    
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
