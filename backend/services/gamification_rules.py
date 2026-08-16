def check_achievements(user_state: dict, streak_was_broken_this_update: bool) -> list[dict]:
    """
    Pure function to evaluate if a user has earned new achievements.
    
    Args:
        user_state: dict containing:
            - total_rounds: int (count of debate rounds completed)
            - current_streak: int
            - current_topic: str (UUID of the current topic, if evaluating a specific debate)
            - verdict: str (verdict of the current debate attempt)
            - topic_attempts: int (number of attempts on the current topic, including the current one)
        streak_was_broken_this_update: bool indicating if the streak reset logic was just triggered
            (used for the Comeback achievement).
            
    Returns:
        A list of dictionaries representing the achievements earned, in the format:
        [{"type": "Achievement Name", "topic_id": "uuid-or-none"}]
    """
    achievements = []
    
    # 1. First Debate Completed
    if user_state.get("total_rounds", 0) == 1:
        achievements.append({
            "type": "First Debate Completed",
            "topic_id": None
        })
        
    # 2. 3-Day Streak
    if user_state.get("current_streak", 0) >= 3:
        achievements.append({
            "type": "3-Day Streak",
            "topic_id": None
        })
        
    # 3. Comeback
    if user_state.get("current_streak", 0) >= 3 and streak_was_broken_this_update:
        achievements.append({
            "type": "Comeback",
            "topic_id": None
        })
        
    # 4. Perfect Score (Per-topic)
    if user_state.get("verdict") == "held_up" and user_state.get("topic_attempts") == 1:
        topic_id = user_state.get("current_topic")
        if topic_id:
            achievements.append({
                "type": "Perfect Score",
                "topic_id": topic_id
            })
            
    return achievements
