#!/bin/bash
# Chess Bot Advanced Strategy Configuration
# Enhanced defensive tactics with human-like transitions and strategic time management

# =============================================================================
# DEFENSIVE FORTRESS STRATEGY (FRUSTRATION MODE)
# =============================================================================
# This configuration creates maximum frustration for opponents with tight defensive play
# Perfect for making stronger opponents waste time and make mistakes

echo "Starting Chess Bot with Advanced Defensive Fortress Strategy..."
python main.py \
  --elo-rating -1 \
  --game-timer-ms 180000 \
  --first-move-w e2e4 \
  --enable-move-delay True \
  --next-game-auto True

# Features:
# - Detects opponent strength automatically
# - Uses stall tactics against stronger opponents (2-4.5x longer thinking time)
# - Creates complex, frustrating positions that are hard to solve
# - Maintains material balance while avoiding simplifications
# - Uses strategic delays based on position complexity

# =============================================================================
# PRESSURE BLITZ STRATEGY (AGAINST WEAKER OPPONENTS)
# =============================================================================
# Uncomment for rapid-fire pressure tactics when opponent is detected as weaker

# echo "Starting Chess Bot with Pressure Blitz Strategy..."
# python main.py \
#   --elo-rating 2200 \
#   --game-timer-ms 120000 \
#   --first-move-w d2d4 \
#   --enable-move-delay True \
#   --next-game-auto True

# Features:
# - Automatically detects weaker opponents
# - Applies immediate pressure with aggressive moves
# - Faster move execution (0.4-0.8x normal timing)
# - Prefers captures, checks, and tactical complications
# - Forces quick decisions from opponent

# =============================================================================
# ADAPTIVE STRATEGY (SMART AUTO-DETECTION)
# =============================================================================
# The bot now automatically switches between strategies based on opponent behavior

# Strategy Detection Logic:
# - Analyzes opponent's time usage patterns
# - If opponent uses >70% of time quickly: Classified as "strong" → Defensive mode
# - If opponent uses <30% of time: Classified as "weak" → Aggressive mode
# - Otherwise: Balanced approach

# =============================================================================
# HUMAN-LIKE TIMING SYSTEM
# =============================================================================
# The bot now calculates realistic human delays based on:

# 1. Position Complexity:
#    - Complex unclear positions (eval ±50): Longer thinking time
#    - Simple tactical positions: Faster execution
#    - Many legal moves (>30): Additional complexity time

# 2. Move Type:
#    - Simple captures/pawn moves: 0.3-1.2 seconds
#    - Complex positional moves: 0.8-2.5 seconds
#    - Critical decisions: Up to 4.5 seconds with stall factor

# 3. Time Management:
#    - Uses max 8% of remaining time per move
#    - Automatically switches to rapid mode if <15% time remaining
#    - Balances stalling vs. time safety

# 4. Strategic Variations:
#    - Against strong opponents: 1.0-3.0 second stall bonus
#    - Against weak opponents: No delays, pure pressure
#    - Human inconsistency: 0.7-1.4x random variation

# =============================================================================
# POSITION EVALUATION FEATURES
# =============================================================================
# The bot now evaluates positions for strategic decisions:

# Defensive Criteria (used against strong/equal opponents):
# - Maintains material balance (+100 points)
# - Creates complex positions with many options (+2 per legal move)
# - Avoids position simplification (+50 for complex positions)
# - Keeps pieces on board (+3 per piece)
# - Prefers complex checks over simple ones

# Aggressive Criteria (used against weak opponents):
# - Prioritizes captures (+150 points)
# - Seeks checks and attacks (+100 for checks)
# - Attacks opponent pieces (+20 per attacked piece)
# - Limits opponent options (+30 for restrictive moves)

# =============================================================================
# ADVANCED TIME PRESSURE TACTICS
# =============================================================================
# Strategic time usage based on game situation:

# Against Stronger Opponents:
# - Uses 2.0-4.5x normal thinking time
# - Adds 1.0-3.0 second "frustration delays"
# - Makes opponent wait for complex, slow games
# - Forces time pressure on stronger players

# Against Weaker Opponents:
# - Uses 0.4-0.8x normal timing for pressure
# - Quick tactical strikes
# - Forces rapid decisions
# - No stalling, pure aggression

# Safety Features:
# - Never uses more than 8% of remaining time per move
# - Automatic emergency fast mode when <15% time left
# - Intelligent time allocation throughout the game

# =============================================================================
# EXAMPLE USAGE SCENARIOS
# =============================================================================

# Scenario 1: Playing Against a Chess Master (2400+ rating)
# - Bot detects slow, careful moves from opponent
# - Switches to maximum defensive mode
# - Creates complex, unclear positions
# - Uses maximum allowed thinking time to frustrate
# - Forces the master to spend time on unclear positions

# Scenario 2: Playing Against a Beginner (1200- rating)  
# - Bot detects fast, careless moves
# - Switches to aggressive pressure mode
# - Seeks immediate tactical strikes
# - Moves quickly to maintain pressure
# - Forces rapid decisions leading to mistakes

# Scenario 3: Equal Opponent (1800-2000 rating)
# - Bot uses balanced defensive approach
# - Moderate thinking times with human-like variation
# - Strategic complexity without extreme stalling
# - Adapts based on opponent's time usage patterns

# =============================================================================
# LOGS AND MONITORING
# =============================================================================
# Watch the logs for strategy information:
# - "Detected opponent strength: [weak/equal/strong]"
# - "Using [defensive/aggressive] strategy"
# - "Applying stall tactics against strong opponent"
# - "Moving quickly to pressure weak opponent"
# - "Move delay: X.XXs (complexity: X.XX, strategy: XXX)"

# =============================================================================
# ANTI-ENGINE DETECTION FEATURES
# =============================================================================
# The bot includes several features to appear more human:
# - Variable timing based on position complexity
# - Realistic delays for different move types
# - Inconsistent timing patterns (not robotic)
# - Human-like reactions to opponent's timing
# - Strategic thinking time that makes sense

echo "Advanced Chess Bot Strategy Loaded!"
echo "The bot will automatically adapt to opponent strength."
echo "Monitor logs to see real-time strategy detection and adaptation."
