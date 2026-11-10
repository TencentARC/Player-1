# Game Info

This document records the benchmark snapshot under `games/benchmark`.

## Benchmark Games

| id | Game | Genre | Summary | Game APIs |
| --- | --- | --- | --- | --- |
| 01 | 01_2048 | Puzzle | Slide and merge tiles toward larger values. | `game_state.level`, `game_state.environment`, `game_state.completion_progress` |
| 02 | 02_another-gentlemans-adventure | Platformer | Retro side-scrolling action shooter with coin pickup and upgrades. | `game_state.score`, `game_state.player`, `game_state.environment`, `metrics.session_stats` |
| 03 | 03_astray | Puzzle | Roll a ball through a 3D maze to the exit. | `game_state.completion_progress`, `metrics.distance_to_goal`, `game_state.environment` |
| 04 | 04_boxel-rebound | Runner | Side-scrolling jump-and-avoid platformer. | `game_state.completion_progress`, `game_state.player.jump_ready`, `game_state.environment` |
| 05 | 05_breakout | Arcade | Classic brick breaker. | `game_state.completion_progress`, `game_state.entities`, `metrics.lives` |
| 06 | 06_captaincallisto | Platformer | Space platformer with coin collection and an exit goal. | `game_state.score`, `metrics.distance_to_goal`, `metrics.lives`, `game_state.environment` |
| 07 | 07_chrome-dino | Runner | Endless Chrome dino runner. | `game_state.score`, `game_state.player`, `game_state.environment`, `metrics.distance` |
| 08 | 08_core-ball | Arcade | Shoot balls into a rotating core without collisions. | `game_state.score`, `game_state.environment`, `game_state.completion_progress` |
| 09 | 09_cubefield | Runner | Endless obstacle dodging through a cube field. | `game_state.score`, `game_state.player`, `game_state.environment` |
| 10 | 10_doodle-jump | Platformer | Keep jumping upward across platforms. | `game_state.score`, `game_state.player.is_dead`, `game_state.environment`, `game_state.entities` |
| 11 | 11_edge-surf | Runner | Microsoft Edge surf-style endless runner. | `game_state.score`, `game_state.mode`, `metrics.distance`, `metrics.lives`, `metrics.boosts`, `metrics.shields` |
| 12 | 12_fireboy-and-watergirl | Simulation | Two-character cooperative puzzle platformer. | `game_state.score`, `game_state.watergirl`, `metrics.fireboy_distance_to_goal`, `metrics.watergirl_distance_to_goal`, `game_state.completion_progress` |
| 13 | 13_flappy-bird | Runner | Endless click-to-fly pipe dodging game. | `game_state.score`, `game_state.environment`, `game_state.entities` |
| 14 | 14_geodash | Platformer | Geometry Dash style rhythm platformer. | `game_state.score`, `game_state.mode`, `game_state.player_die`, `metrics.distance`, `metrics.points`, `metrics.stars` |
| 15 | 15_google-snake | Arcade | Classic snake game. | `game_state.environment`, `game_state.entities`, `metrics.snake_length`, `metrics.speed` |
| 16 | 16_hextris | Puzzle | Fast hexagon-based rotation and clearing game. | `game_state.score`, `game_state.player`, `game_state.environment` |
| 17 | 17_mario-game | Platformer | Mario platform adventure. | `game_state.score`, `game_state.environment`, `metrics.coins`, `metrics.lives`, `metrics.time_left_s`, `game_state.completion_progress` |
| 18 | 18_minecraft-clone-glm | Simulation | First-person mining and resource gathering. | `game_state.inventory`, `game_state.environment`, `metrics.item_gains`, `metrics.hotbar_usage` |
| 19 | 19_minesweeper | Puzzle | Classic Minesweeper logic puzzle. | `game_state.score`, `metrics.revealed_safe_cells`, `metrics.correct_flags`, `metrics.remaining_mines`, `game_state.completion_progress` |
| 20 | 20_monkey-mart | Simulation | Manage a monkey supermarket, restock, and collect money. | `metrics.primary_score`, `game_state.money`, `game_state.money_total_earned`, `game_state.money_scan_status` |
| 21 | 21_ns-shaft | Runner | Survival arcade game about falling onto safe platforms. | `gameTimeMs`, `game_state.player.life`, `game_state.environment` |
| 22 | 22_ovo | Platformer | Fast parkour platformer with wall slides and jumps. | `game_state.level`, `game_state.coins`, `game_state.distance_to_exit`, `game_state.completion_progress` |
| 23 | 23_pacman | Arcade | Classic Pac-Man maze chase. | `game_state.score`, `game_state.maze_index`, `metrics.high_score`, `status` |
| 24 | 24_restless-wing-syndrome | Platformer | Platformer with automatic wing flaps. | `game_state.level`, `game_state.player.flap_meter`, `game_state.environment`, `game_state.completion_progress` |
| 25 | 25_rocket-league-2d | Arcade | 2D car soccer. | `metrics.primary_score`, `metrics.goals_against`, `metrics.distance_to_goal`, `game_state.player.boost`, `game_state.player.gas` |
| 26 | 26_run-3 | Runner | Endless running through space tunnels. | `metrics.primary_score`, `metrics.deaths`, `metrics.attempts`, `game_state.environment` |
| 27 | 27_stack | Puzzle | Timing-based tower stacking game. | `game_state.score`, `game_state.environment.blocks_count`, `game_state.environment.top_stable_block`, `game_state.environment.camera_y` |
| 28 | 28_temple-run-2 | Runner | Endless runner with turns, jumps, and slides. | `metrics.score`, `game_state.distance`, `metrics.stumbles_this_run`, `metrics.powerups_collected_this_run`, `metrics.resurrects_this_run` |
| 29 | 29_tetris | Puzzle | Classic Tetris. | `game_state.score`, `game_state.environment.board`, `game_state.environment.preview_queue`, `metrics.lines_remaining` |
| 30 | 30_vex-3 | Platformer | High-speed trap-heavy platformer. | `metrics.checkpoints_passed`, `metrics.distance_to_goal`, `metrics.deaths`, `game_state.environment` |
| 31 | 31_wolf3d | Simulation | Wolfenstein-style first-person shooter. | `metrics.kills`, `metrics.health`, `metrics.ammo`, `metrics.lives`, `game_state.environment.nearest_enemy`, `game_state.completion_progress` |
| 32 | 32_wordle | Puzzle | Five-letter word guessing game. | `metrics.letters_correct`, `game_state.environment.letters`, `game_state.environment.cell_states`, `game_state.environment.current_guess_length` |
| 33 | 33_worlds-hardest-game | Arcade | High-difficulty maze with enemies and coin collection. | `game_state.level`, `game_state.environment`, `metrics.coins`, `game_state.completion_progress` |
| 34 | 34_worlds-hardest-game-2 | Arcade | Sequel with more complex routes and objectives. | `metrics.coins`, `metrics.keys`, `game_state.environment`, `game_state.completion_progress` |
