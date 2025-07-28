import asyncio
import collections
import concurrent.futures
import itertools
import os
import pdb
import random
import sys
import threading
import traceback
import typing
from time import time, sleep

import logging
import selenium.common.exceptions
import selenium.webdriver.common.devtools.v119 as devtools
import typer
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.remote.webdriver import WebDriver
import selenium.webdriver.support.expected_conditions as EC

import stockfish
import chess
import json

selenium_logger = logging.getLogger('selenium')
selenium_logger.setLevel(logging.INFO)

logging.getLogger('selenium').setLevel(logging.DEBUG)
logging.getLogger('selenium.webdriver.remote').setLevel(logging.DEBUG)
logging.getLogger('selenium.webdriver.common').setLevel(logging.DEBUG)

url = "https://www.chess.com/"
stockfish_dir = "./stockfish"
stockfish_path = stockfish_dir + "/stockfish"
executor = concurrent.futures.ThreadPoolExecutor(5)

# Decrease/increase this parameter if the default move delay is too fast / too slow
MOVE_DELAY_MULTIPLIER = 1.0

PREVIOUS_FEN_POSITIONS = collections.defaultdict(lambda: 0)
NEW_GAME_BUTTON_CLICK_TIME = time()
LAST_REFRESH_TIME = 0  # Add debouncing for refresh
LAST_GAME_STATE = {}  # Store last game state for recovery
RECOVERY_ATTEMPTS = 0  # Track recovery attempts
MAX_RECOVERY_ATTEMPTS = 5  # Maximum recovery attempts before reset

# the browser will be refreshed after 45 seconds of matchmaking if no match was found.
NEW_GAME_BUTTON_CLICK_TIMEOUT = 45
REFRESH_COOLDOWN = 10  # Minimum seconds between refreshes
PAGE_LOAD_TIMEOUT = 30  # Maximum time to wait for page load

class C:
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    board = "board"
    flipped = "flipped"
    outerHTML = "outerHTML"
    square = "square-"
    piece = "piece"
    hover = "hover-"
    highlight = "highlight"
    class_ = "class"
    space = " "
    controls_xpath = "//div[@class='game-controls-controller-component' or @class='live-game-buttons-component']"
    new_game_buttons_xpath = "//div[button[span[contains(text(),'New') or contains(text(),'Decline') or contains(text(),'Rem')]]]"
    new_game_button_sub_xpath = "./button[span[contains(text(), \"%s\")]]"
    some_id = "p1234"
    promotion_moves = ["1", "8"]
    scr_xpath = """
    _iter = document.evaluate('%s', document, null, 
        XPathResult.UNORDERED_NODE_ITERATOR_TYPE, null);
    _lst = [];
    while(1) {
        e = _iter.iterateNext();
        if (!e) break;
        _lst.push(e.getAttribute("class"));
    }
    return _lst
    """.strip()
    xpath_highlight = f'//*[contains(@class,"{highlight}")]'
    xpath_piece = '//div[contains(@class,"piece") and (contains(@class, "%d") or contains(@class, "%d"))]'
    js_add_ptr = """
    var board = document.getElementsByClassName('%s').item(0);
    var piece = document.createElement('div');

    piece.setAttribute('class', '%s');
    board.appendChild(piece);
    """
    js_rm_ptr = """
    const board = document.getElementsByClassName('%s').item(0);
    const to_rm = document.getElementsByClassName('%s');
    for (var i = 0; i < to_rm.length; i++) {
       board.removeChild(to_rm.item(i));
    }
    """
    white_pawn = "wp"
    black_queen = "bq"
    white_queen = "wq"
    promotion_window = "promotion-window"
    promotion_move_queen = "q"
    wait_1s = 1
    wait_2s = 2
    wait_5s = 5
    wait_240s = 240
    wait_50ms = 0.05
    exit_delay = 10
    task_wait = "task_wait"
    num_to_let = dict(zip(range(1, 9), "abcdefgh"))
    let_to_num = dict((v, k) for k, v in num_to_let.items())


class LogFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    green = "\x1b[32m"
    blue = "\x1b[34m"
    cyan = "\x1b[36m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = " %(asctime)s [%(name)s]: %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG:
            reset + "%(asctime)s " +
            yellow + "[%(levelname)s]" +
            cyan + " [%(name)s," +
            cyan + " %(filename)s:%(lineno)d]:" + reset +
            grey + " %(message)s" + reset,
        logging.INFO:
            reset + "%(asctime)s " +
            green + "[%(levelname)s] [" +
            green + "%(name)s," +
            green + " %(filename)s:%(lineno)d]" + reset +
            grey + ": %(message)s" + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }
    DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt=LogFormatter.DATE_FORMAT)
        return formatter.format(record)


stream = logging.StreamHandler(stream=sys.stdout)
stream.setFormatter(LogFormatter())
Log = logging.getLogger('chess-log')
Log.setLevel(logging.DEBUG)
Log.addHandler(stream)

if not os.path.exists(stockfish_path) and os.path.exists(stockfish_path + ".exe"):
    stockfish_path = stockfish_path + ".exe"

Log.info(stockfish_path)
if not os.path.exists(stockfish_path):
    Log.info("Consider copying the Stockfish binaries to "
             "the ./stockfish directory of the project path.")
    Log.info("The Stockfish binary name must be exactly \"stockfish\", the file's extension removed.")
    try:
        os.mkdir(stockfish_dir)
    except FileExistsError:
        pass
    Log.error(traceback.format_exception(FileNotFoundError(stockfish_path)))
    input()
    exit(1)


def is_docker():
    return os.environ.get("hub_host", None) is not None


def execute_cmd_cdp_workaround(drv: WebDriver, cmd, params: dict):
    resource = "/session/%s/chromium/send_command_and_get_result" % drv.session_id
    url_ = drv.command_executor._url + resource
    body = json.dumps({'cmd': cmd, 'params': params})
    response = drv.command_executor._request('POST', url_, body)
    return response.get('value')


def init_remote_driver(hub_url, options_, max_retries=5, retry_delay=2):
    for _ in range(max_retries):
        try:
            return webdriver.Remote(command_executor=hub_url, options=options_)
        except:
            Log.error(traceback.format_exc(limit=2))
            sleep(retry_delay)
    raise ConnectionError


def setup_driver():
    profile_dir = os.path.join(os.getcwd(), "Profile/Selenium")
    options = Options()
    service = Service()
    options.add_argument("--mute-audio")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option("prefs", {
        "intl.accept_languages": ["en-US"]
    })
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=en")
    options.add_argument("--accept-lang=en-US")
    
    if is_docker():
        options.add_argument("--start-maximized")
        host = os.environ["hub_host"]
        port = os.environ["hub_port"]
        Log.info(f"{host} {port}")
        chrome_driver = init_remote_driver(f"http://{host}:{port}/wd/hub", options)
        execute_cmd_cdp_workaround(chrome_driver, "Network.setUserAgentOverride", {
            "userAgent": C.user_agent
        })
    else:
        options.add_argument("--user-data-dir=" + profile_dir)
        options.add_argument("--profile-directory=Default")
        chrome_driver = webdriver.Chrome(service=service, options=options)
        chrome_driver.execute_cdp_cmd("Network.setUserAgentOverride", {
            "userAgent": C.user_agent
        })
    chrome_driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    Log.info(chrome_driver.execute_script("return navigator.userAgent;"))
    return chrome_driver


def trace_exec_time(func):
    def _wrapper(*a, **kw):
        t0 = time()
        res = func(*a, **kw)
        t0 = time() - t0
        Log.debug(f"<{func.__name__}> call took %.6fs" % t0)
        return res

    return _wrapper


def set_elo(engine, loop_id):
    elo = {
    }
    if loop_id in elo:
        engine.set_elo_rating(elo[loop_id])


class CustomTask(asyncio.Task):
    def __init__(self, data=None, *a, **kw):
        super().__init__(*a, **kw)
        self.data = data


async def wait_until(drv, delay_seconds: float, condition):
    async def wait_until_sub(drv_, delay_, condition_):
        return WebDriverWait(drv_, delay_).until(condition_)

    return await CustomTask(
        data=(time(), delay_seconds),
        name=C.task_wait, coro=wait_until_sub(drv, delay_seconds, condition)
    )


async def task_canceller():
    asyncio_loop = asyncio.get_event_loop()
    while asyncio_loop is None or not asyncio_loop.is_closed():
        await asyncio.sleep(3)
        try:
            if asyncio_loop is None:
                continue
            task_wait = next(filter(
                lambda x: asyncio.Task.get_name(x) == C.task_wait,
                asyncio.all_tasks(asyncio_loop)
            ), None)
            if task_wait is None:
                continue
            if not isinstance(task_wait, CustomTask):
                Log.error(f"Task {task_wait} is not an instance of {CustomTask}")
                task_wait.cancel()
                continue
            timestamp, delay = task_wait.data
            if time() - timestamp > delay + 1 and not task_wait.cancelled():
                Log.debug(f"{task_wait} is not cancellable. Unknown error, possibly a Selenium WebDriver process issue")
                task_wait.cancel()
                task_wait.cancel()
                continue
            if time() - timestamp > delay + 1:
                Log.debug(f"Attempting to cancel the task: {task_wait}")
                task_wait.cancel()
                continue
            Log.debug(f"{task_wait}")
        except asyncio.CancelledError as e:
            raise e
        except:
            Log.error(traceback.format_exc())


@trace_exec_time
def get_last_move(drv: webdriver.Chrome):
    highlighted = drv.find_elements(By.CLASS_NAME, C.highlight)

    if len(highlighted) < 2:
        Log.error("len(highlighted)<2")
        raise RuntimeError
    if len(highlighted) > 2:
        Log.error("len(highlighted)>2")
        Log.error([x.get_attribute("outerHTML") for x in highlighted])
        highlighted = highlighted[:2]

    first, second = highlighted

    def get_tile_number(e) -> int:
        return int(e.get_attribute(C.class_)[-2:])

    t1, t2 = tuple(get_tile_number(x) for x in highlighted)
    piece_xpath = C.xpath_piece % (t1, t2)
    piece = drv.find_element(By.XPATH, piece_xpath)
    if str(t1) in piece.get_attribute(C.class_):
        first, second = second, first
    f = lambda x: C.num_to_let[int(x[0])] + x[1]
    _f = lambda element: (
        f(x.lstrip(C.square)) for x in element.get_attribute(C.class_).split()
        if x.startswith(C.square)
    ).__iter__().__next__()
    tile1, tile2 = _f(first), _f(second)
    return tile1, tile2


def min_n_elements_exist(by: By, selector: typing.Any, n: int = 1):
    return lambda drv: len(drv.find_elements(by, selector)) >= n


def find_elements(by: By, selector: typing.Any, single=False):
    return lambda drv: drv.find_element(by, selector) if single else drv.find_elements(by, selector)


def find_element_and_click(by: By, selector: typing.Any):
    def find_element_and_click_sub(drv):
        try:
            element = drv.find_element(by, selector)
            element.click()
            return True
        except:
            return False

    return find_element_and_click_sub


async def handle_promotion_window(driver_):
    try:
        promotion = await wait_until(
            driver_,
            C.wait_50ms,
            EC.visibility_of_element_located((By.CLASS_NAME, C.promotion_window))
        )
        sleep(0.2)
        item = promotion.find_elements(By.CLASS_NAME, C.black_queen)
        item = item[0] if len(item) > 0 else None
        if item is None:
            item = promotion.find_elements(By.CLASS_NAME, C.white_queen)
            item = item[0] if len(item) > 0 else None
        if item is None:
            raise RuntimeError
        item.click()
    except selenium.common.exceptions.TimeoutException:
        pass
    except selenium.common.exceptions.ElementNotInteractableException:
        await handle_promotion_window(driver_)


def controls_visible(driver):
    try:
        el = driver.find_element(By.XPATH, C.new_game_buttons_xpath)
        return el.is_displayed()
    except selenium.common.exceptions.NoSuchElementException:
        return False
    except selenium.common.exceptions.StaleElementReferenceException:
        return False

def is_game_over(driver):
    """Enhanced game over detection to prevent unnecessary refreshes"""
    try:
        # Check for multiple game over indicators
        game_over_selectors = [
            C.new_game_buttons_xpath,
            "//div[contains(@class, 'game-over')]",
            "//div[contains(@class, 'game-ended')]", 
            "//div[contains(text(), 'Game Over')]",
            "//button[contains(text(), 'New Game')]",
            "//button[contains(text(), 'Rematch')]",
            "//div[contains(@class, 'post-game')]"
        ]
        
        for selector in game_over_selectors:
            try:
                elements = driver.find_elements(By.XPATH, selector)
                if elements and any(el.is_displayed() for el in elements):
                    return True
            except:
                continue
                
        # Check if we're in a different page (like analysis page)
        current_url = driver.current_url
        if any(indicator in current_url for indicator in ['analysis', 'game/', 'review']):
            return True
            
        return False
    except:
        return False

def is_page_loaded_properly(driver):
    """Check if chess.com page is loaded properly"""
    try:
        # Check for essential elements
        essential_selectors = [
            "body",
            "//div[contains(@class, 'board') or contains(@class, 'game') or contains(@class, 'play')]",
            "//a[contains(@href, 'play') or contains(@href, 'game')]"
        ]
        
        for selector in essential_selectors:
            try:
                if selector.startswith("//"):
                    elements = driver.find_elements(By.XPATH, selector)
                else:
                    elements = driver.find_elements(By.TAG_NAME, selector)
                if not elements:
                    return False
            except:
                return False
                
        # Check if we're on chess.com domain
        current_url = driver.current_url
        if "chess.com" not in current_url:
            return False
            
        return True
    except:
        return False

def save_game_state(engine, move_number=0, timer=0):
    """Save current game state for recovery"""
    global LAST_GAME_STATE
    try:
        LAST_GAME_STATE = {
            'fen': engine.get_fen_position(),
            'move_number': move_number,
            'timer': timer,
            'timestamp': time(),
            'previous_positions': dict(PREVIOUS_FEN_POSITIONS)
        }
        Log.debug(f"Game state saved: move {move_number}, timer {timer/1000:.1f}s")
    except Exception as e:
        Log.error(f"Failed to save game state: {e}")

def restore_game_state(engine):
    """Restore game state after recovery"""
    global LAST_GAME_STATE, PREVIOUS_FEN_POSITIONS
    try:
        if not LAST_GAME_STATE:
            Log.info("No saved game state to restore")
            return False
            
        # Check if saved state is recent (within 10 minutes)
        if time() - LAST_GAME_STATE.get('timestamp', 0) > 600:
            Log.info("Saved game state is too old, starting fresh")
            return False
            
        engine.set_fen_position(LAST_GAME_STATE['fen'])
        PREVIOUS_FEN_POSITIONS.clear()
        PREVIOUS_FEN_POSITIONS.update(LAST_GAME_STATE.get('previous_positions', {}))
        
        Log.info(f"Game state restored: move {LAST_GAME_STATE['move_number']}, "
                f"timer {LAST_GAME_STATE['timer']/1000:.1f}s")
        return True
    except Exception as e:
        Log.error(f"Failed to restore game state: {e}")
        return False

def is_game_in_progress(driver):
    """Check if a game is currently in progress"""
    try:
        # Look for board element
        board_elements = driver.find_elements(By.CLASS_NAME, C.board)
        if not board_elements:
            return False
            
        # Look for game controls that indicate active game
        controls = driver.find_elements(By.XPATH, C.controls_xpath)
        if not controls:
            return False
            
        # Check if we can find pieces on the board
        pieces = driver.find_elements(By.XPATH, '//div[contains(@class,"piece")]')
        if len(pieces) < 10:  # Should have at least some pieces
            return False
            
        # Make sure we're not on a game over screen
        if is_game_over(driver):
            return False
            
        return True
    except:
        return False

def recover_from_reload(driver, engine):
    """Attempt to recover after page reload"""
    global RECOVERY_ATTEMPTS, LAST_REFRESH_TIME
    
    try:
        RECOVERY_ATTEMPTS += 1
        Log.info(f"Attempting recovery #{RECOVERY_ATTEMPTS} after page reload...")
        
        # Wait for page to load
        if not wait_for_page_load(driver):
            Log.error("Page failed to load properly during recovery")
            return False
            
        # Navigate to play page if not already there
        current_url = driver.current_url
        if "play" not in current_url and "game" not in current_url:
            Log.info("Navigating to play page...")
            driver.get("https://www.chess.com/play")
            if not wait_for_page_load(driver):
                return False
                
        # Try to restore game state
        if restore_game_state(engine):
            Log.info("Game state restored successfully")
            
            # Check if we can resume the current game
            if is_game_in_progress(driver):
                Log.info("Found active game, attempting to resume...")
                RECOVERY_ATTEMPTS = 0  # Reset counter on successful recovery
                return True
                
        # If no active game found, prepare for new game
        Log.info("No active game found, will start new game")
        RECOVERY_ATTEMPTS = 0
        LAST_REFRESH_TIME = time()  # Update to prevent immediate refresh
        return True
        
    except Exception as e:
        Log.error(f"Recovery attempt failed: {e}")
        return False

def enhanced_refresh_with_recovery(driver, engine, reason="timeout"):
    """Enhanced refresh with recovery capabilities"""
    global LAST_REFRESH_TIME, RECOVERY_ATTEMPTS
    
    current_time = time()
    
    # Check if we should attempt refresh
    if current_time - LAST_REFRESH_TIME < REFRESH_COOLDOWN:
        Log.debug(f"Refresh cooldown active, skipping refresh (last: {current_time - LAST_REFRESH_TIME:.1f}s ago)")
        return False
        
    if RECOVERY_ATTEMPTS >= MAX_RECOVERY_ATTEMPTS:
        Log.warning("Max recovery attempts reached, forcing longer cooldown")
        if current_time - LAST_REFRESH_TIME < REFRESH_COOLDOWN * 3:
            return False
            
    try:
        Log.info(f"Performing enhanced refresh due to: {reason}")
        
        # Save current state before refresh
        try:
            save_game_state(engine)
        except:
            pass
            
        # Perform refresh
        driver.refresh()
        LAST_REFRESH_TIME = current_time
        
        # Wait for page load and attempt recovery
        return recover_from_reload(driver, engine)
        
    except Exception as e:
        Log.error(f"Enhanced refresh failed: {e}")
        RECOVERY_ATTEMPTS += 1
        return False

def get_fen_deriv(fen: str, move_uci: str) -> str:
    board = chess.Board(fen)
    move = chess.Move.from_uci(move_uci)
    #assert move in board.legal_moves:
    board.push(move)
    return board.fen()

def evaluate_position_complexity(engine: stockfish.Stockfish) -> float:
    """Evaluate position complexity for strategic thinking time"""
    try:
        # Get evaluation score
        evaluation = engine.get_evaluation()
        if evaluation['type'] == 'mate':
            return 0.5  # Tactical positions need less thinking
        
        score = abs(evaluation['value']) if evaluation['value'] else 0
        
        # Complex positions have evaluations closer to 0 (unclear positions)
        if score < 50:  # Very unclear position
            complexity = 1.0
        elif score < 150:  # Somewhat unclear
            complexity = 0.8
        elif score < 300:  # Clear advantage
            complexity = 0.6
        else:  # Winning/losing position
            complexity = 0.4
            
        # Add complexity based on number of legal moves
        fen = engine.get_fen_position()
        import chess
        board = chess.Board(fen)
        num_moves = len(list(board.legal_moves))
        
        if num_moves > 30:  # Many options = complex
            complexity += 0.2
        elif num_moves < 10:  # Few options = simple
            complexity -= 0.1
            
        return min(max(complexity, 0.3), 1.0)
    except:
        return 0.7  # Default moderate complexity

def get_strategic_move(engine: stockfish.Stockfish, top_moves: list, strategy_type: str = "balanced") -> str:
    """Select move based on comprehensive chess strategy implementation"""
    try:
        current_fen = engine.get_fen_position()
        board = chess.Board(current_fen)
        move_number = board.fullmove_number
        
        best_move = None
        best_score = -999999
        
        for move_str in top_moves:
            move = chess.Move.from_uci(move_str)
            board.push(move)
            
            score = 0
            
            # ♟️ 1. CENTER CONTROL (Menguasai Pusat)
            center_squares = [chess.E4, chess.D4, chess.E5, chess.D5]
            extended_center = [chess.C3, chess.C4, chess.C5, chess.C6, chess.F3, chess.F4, chess.F5, chess.F6]
            
            if move.to_square in center_squares:
                score += 80  # Major center control
            elif move.to_square in extended_center:
                score += 40  # Extended center control
                
            # Check if move attacks center squares
            for center_sq in center_squares:
                if board.is_attacked_by(board.turn, center_sq):
                    score += 25
            
            # ♞ 2. PIECE ACTIVITY (Aktivasi Perwira)
            piece = board.piece_at(move.to_square)
            if piece:
                # Development bonus for knights and bishops
                if piece.piece_type in [chess.KNIGHT, chess.BISHOP] and move_number <= 12:
                    score += 60
                    
                # Knight outposts (protected squares in enemy territory)
                if piece.piece_type == chess.KNIGHT:
                    if piece.color == chess.WHITE and chess.square_rank(move.to_square) >= 4:
                        if board.is_attacked_by(chess.WHITE, move.to_square):
                            score += 45
                    elif piece.color == chess.BLACK and chess.square_rank(move.to_square) <= 3:
                        if board.is_attacked_by(chess.BLACK, move.to_square):
                            score += 45
                
                # Bishop on long diagonal
                if piece.piece_type == chess.BISHOP:
                    long_diagonals = [chess.A1, chess.B2, chess.C3, chess.D4, chess.E5, chess.F6, chess.G7, chess.H8,
                                    chess.A8, chess.B7, chess.C6, chess.D5, chess.E4, chess.F3, chess.G2, chess.H1]
                    if move.to_square in long_diagonals:
                        score += 35
            
            # ♚ 3. KING SAFETY (Keamanan Raja)
            # Castling rights preservation
            if board.has_kingside_castling_rights(board.turn) or board.has_queenside_castling_rights(board.turn):
                if move_number <= 10:
                    score += 30  # Preserve castling options
            
            # King safety evaluation
            king_square = board.king(board.turn)
            if king_square:
                # Penalty for exposed king
                attackers = len(board.attackers(not board.turn, king_square))
                score -= attackers * 15
                
                # Bonus for king behind pawn shield (after castling)
                if piece and piece.piece_type == chess.KING:
                    if chess.square_file(move.to_square) in [chess.FILE_G, chess.FILE_C]:  # Castled position
                        score += 50
            
            # 🧱 4. PAWN STRUCTURE (Struktur Pion)
            pawn_structure_score = 0
            
            # Avoid doubled pawns
            for file in range(8):
                white_pawns = len([sq for sq in chess.SquareSet(board.pieces(chess.PAWN, chess.WHITE)) 
                                 if chess.square_file(sq) == file])
                black_pawns = len([sq for sq in chess.SquareSet(board.pieces(chess.PAWN, chess.BLACK)) 
                                 if chess.square_file(sq) == file])
                
                if board.turn == chess.WHITE and white_pawns > 1:
                    pawn_structure_score -= 20
                elif board.turn == chess.BLACK and black_pawns > 1:
                    pawn_structure_score -= 20
            
            # Passed pawn bonus
            for pawn_sq in board.pieces(chess.PAWN, board.turn):
                if is_passed_pawn(board, pawn_sq, board.turn):
                    rank = chess.square_rank(pawn_sq)
                    if board.turn == chess.WHITE:
                        pawn_structure_score += (rank - 1) * 15  # More advanced = better
                    else:
                        pawn_structure_score += (6 - rank) * 15
            
            score += pawn_structure_score
            
            # 🧭 5. POSITIONAL PLAY (Permainan Posisional)
            # Control of key squares
            key_squares = center_squares + extended_center
            controlled_squares = sum(1 for sq in key_squares if board.is_attacked_by(board.turn, sq))
            score += controlled_squares * 8
            
            # Open files for rooks
            if piece and piece.piece_type == chess.ROOK:
                file = chess.square_file(move.to_square)
                if not any(p.piece_type == chess.PAWN for p in board.pieces(chess.PAWN, chess.WHITE) 
                          if chess.square_file(p) == file) and \
                   not any(p.piece_type == chess.PAWN for p in board.pieces(chess.PAWN, chess.BLACK) 
                          if chess.square_file(p) == file):
                    score += 40  # Open file bonus
            
            # 💥 6. TACTICAL MOTIFS (Motif Taktis)
            # Checks
            if board.is_check():
                score += 70
            
            # Captures
            if board.is_capture(move):
                captured_piece = board.piece_at(move.to_square)
                if captured_piece:
                    piece_values = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 300, 
                                  chess.ROOK: 500, chess.QUEEN: 900}
                    score += piece_values.get(captured_piece.piece_type, 0) // 10
            
            # Forks (attacking multiple pieces)
            attacked_pieces = 0
            for sq in chess.SQUARES:
                if board.is_attacked_by(board.turn, sq):
                    target_piece = board.piece_at(sq)
                    if target_piece and target_piece.color != board.turn:
                        attacked_pieces += 1
            if attacked_pieces >= 2:
                score += attacked_pieces * 25  # Fork bonus
            
            # 🤖 7. ENGINE-INSPIRED PLAY (Gaya Engine)
            if strategy_type == "engine_style":
                # Aggressive pawn advances
                if piece and piece.piece_type == chess.PAWN:
                    if move.to_square in [chess.H4, chess.H5, chess.A4, chess.A5]:
                        score += 30  # Wing pawn advances
                
                # Unconventional but sound moves
                if move_str not in top_moves[:3]:  # Not the most obvious move
                    score += 20
            
            # ⚔️ 8. INITIATIVE (Menjaga Inisiatif)
            if strategy_type == "aggressive":
                # Limit opponent options
                opponent_moves_before = len(list(board.legal_moves))
                board.pop()
                board.push(move)
                opponent_moves_after = len(list(board.legal_moves))
                
                if opponent_moves_after < opponent_moves_before:
                    score += (opponent_moves_before - opponent_moves_after) * 15
                
                # Attacks on opponent pieces
                attacked_value = 0
                for sq in chess.SQUARES:
                    if board.is_attacked_by(board.turn, sq):
                        target = board.piece_at(sq)
                        if target and target.color != board.turn:
                            piece_values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, 
                                          chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 20}
                            attacked_value += piece_values.get(target.piece_type, 0)
                score += attacked_value * 8
            
            # 🏁 9. ENDGAME CONSIDERATIONS (Penguasaan Endgame)
            total_pieces = len(board.piece_map())
            if total_pieces <= 12:  # Endgame
                # King activity in endgame
                if piece and piece.piece_type == chess.KING:
                    # King should be active in endgame
                    king_activity = 0
                    for sq in chess.SQUARES:
                        if board.is_attacked_by(board.turn, sq):
                            king_activity += 1
                    score += king_activity * 5
                
                # Pawn promotion potential
                if piece and piece.piece_type == chess.PAWN:
                    rank = chess.square_rank(move.to_square)
                    if board.turn == chess.WHITE and rank >= 6:
                        score += (rank - 5) * 40
                    elif board.turn == chess.BLACK and rank <= 1:
                        score += (2 - rank) * 40
            
            # Strategy-specific adjustments
            if strategy_type == "defensive":
                # Defensive bonuses
                if not board.is_capture(move):
                    score += 30  # Prefer non-capturing moves
                
                piece_count = len(board.piece_map())
                score += piece_count * 2  # Keep pieces on board
                
            elif strategy_type == "aggressive":
                # Aggressive bonuses
                if board.is_capture(move) or board.is_check():
                    score += 50
                
                # Prefer moves that create threats
                threats = 0
                for sq in chess.SQUARES:
                    if board.is_attacked_by(board.turn, sq):
                        target = board.piece_at(sq)
                        if target and target.color != board.turn:
                            threats += 1
                score += threats * 12
            
            board.pop()  # Undo the move
            
            if score > best_score:
                best_score = score
                best_move = move_str
                
        return best_move or top_moves[0]
    except Exception as e:
        Log.error(f"Strategic move selection failed: {e}")
        return top_moves[0]

def is_passed_pawn(board: chess.Board, pawn_square: int, color: bool) -> bool:
    """Check if a pawn is passed (no enemy pawns can stop it)"""
    try:
        file = chess.square_file(pawn_square)
        rank = chess.square_rank(pawn_square)
        
        # Check files: same file and adjacent files
        check_files = [f for f in [file-1, file, file+1] if 0 <= f <= 7]
        
        enemy_color = not color
        
        if color == chess.WHITE:
            # Check squares ahead of the pawn
            for check_file in check_files:
                for check_rank in range(rank + 1, 8):
                    check_square = chess.square(check_file, check_rank)
                    piece = board.piece_at(check_square)
                    if piece and piece.piece_type == chess.PAWN and piece.color == enemy_color:
                        return False
        else:
            # Check squares ahead of the pawn (for black)
            for check_file in check_files:
                for check_rank in range(0, rank):
                    check_square = chess.square(check_file, check_rank)
                    piece = board.piece_at(check_square)
                    if piece and piece.piece_type == chess.PAWN and piece.color == enemy_color:
                        return False
        
        return True
    except:
        return False

def get_defensive_move(engine: stockfish.Stockfish, top_moves: list) -> str:
    """Select most defensive/frustrating move using strategic evaluation"""
    return get_strategic_move(engine, top_moves, "defensive")

def get_aggressive_move(engine: stockfish.Stockfish, top_moves: list) -> str:
    """Select most aggressive/pressure move using strategic evaluation"""
    return get_strategic_move(engine, top_moves, "aggressive")

def detect_opponent_strength(timer_remaining: float, game_timer: float) -> str:
    """Detect if opponent is stronger/weaker based on time usage patterns and move quality"""
    time_used_ratio = 1.0 - (timer_remaining / game_timer)
    
    # Enhanced heuristics for opponent strength detection
    if time_used_ratio > 0.8:  # Uses most of time - very careful/strong player
        return "strong"
    elif time_used_ratio > 0.6:  # Uses significant time - strong player
        return "strong"  
    elif time_used_ratio < 0.2:  # Uses very little time - likely weak/impatient
        return "weak"
    elif time_used_ratio < 0.4:  # Uses little time - possibly weak
        return "weak"
    else:
        return "equal"   # Balanced time usage

def is_opening_position(engine: stockfish.Stockfish) -> bool:
    """Check if we're still in opening phase for faster moves"""
    try:
        fen = engine.get_fen_position()
        board = chess.Board(fen)
        
        # Opening criteria:
        # 1. Less than 10 moves played
        # 2. Most pieces still on starting squares
        # 3. No major piece exchanges yet
        
        move_number = board.fullmove_number
        if move_number > 8:
            return False
            
        # Count pieces to see if we're still in opening
        piece_count = len(board.piece_map())
        if piece_count < 28:  # Started with 32, so some exchanges happened
            return False
            
        return True
    except:
        return False

def get_quick_opening_move(engine: stockfish.Stockfish, top_moves: list, move_number: int) -> str:
    """Get opening move quickly for moves 1-8 with strategic principles"""
    try:
        if not top_moves:
            return engine.get_best_move()
            
        # For very early moves (1-3), use opening repertoire
        if move_number <= 3:
            return get_strategic_move(engine, top_moves[:3], "balanced")
            
        # For moves 4-8, apply opening principles
        current_fen = engine.get_fen_position()
        board = chess.Board(current_fen)
        
        best_move = None
        best_score = -9999
        
        for move_str in top_moves[:5]:  # Check top 5 moves for speed
            try:
                move = chess.Move.from_uci(move_str)
                board.push(move)
                
                score = 0
                piece = board.piece_at(move.to_square)
                
                # 📘 OPENING PREPARATION PRINCIPLES
                # 1. Control center
                center_squares = [chess.E4, chess.D4, chess.E5, chess.D5]
                if move.to_square in center_squares:
                    score += 100
                elif move.to_square in [chess.C3, chess.C4, chess.C5, chess.C6, chess.F3, chess.F4, chess.F5, chess.F6]:
                    score += 50
                    
                # 2. Develop pieces (knights before bishops)
                if piece:
                    if piece.piece_type == chess.KNIGHT and move_number <= 6:
                        score += 80
                    elif piece.piece_type == chess.BISHOP and move_number <= 10:
                        score += 60
                    elif piece.piece_type == chess.QUEEN and move_number <= 8:
                        score -= 40  # Don't develop queen too early
                
                # 3. Castling preparation
                if move.to_square in [chess.G1, chess.C1, chess.G8, chess.C8]:  # Castling moves
                    if move_number >= 4:
                        score += 90
                
                # 4. Don't move same piece twice
                from_square = move.from_square
                piece_moved = board.piece_at(from_square)
                if piece_moved and piece_moved.piece_type in [chess.KNIGHT, chess.BISHOP]:
                    # Check if this piece was moved before
                    starting_squares = {
                        chess.WHITE: {chess.KNIGHT: [chess.B1, chess.G1], chess.BISHOP: [chess.C1, chess.F1]},
                        chess.BLACK: {chess.KNIGHT: [chess.B8, chess.G8], chess.BISHOP: [chess.C8, chess.F8]}
                    }
                    if from_square not in starting_squares.get(piece_moved.color, {}).get(piece_moved.piece_type, []):
                        score -= 30  # Penalty for moving developed pieces again
                
                # 5. Avoid blocking your own pieces
                if piece and piece.piece_type == chess.PAWN:
                    # Don't block bishops with pawns
                    if move.to_square in [chess.E3, chess.D3, chess.E6, chess.D6] and move_number <= 6:
                        score -= 25
                
                # 6. Safe development (don't hang pieces)
                if board.is_attacked_by(not board.turn, move.to_square):
                    attackers = len(board.attackers(not board.turn, move.to_square))
                    defenders = len(board.attackers(board.turn, move.to_square))
                    if attackers > defenders:
                        score -= 50
                
                board.pop()
                
                if score > best_score:
                    best_score = score
                    best_move = move_str
                    
            except:
                continue
                
        return best_move or top_moves[0]
    except:
        return top_moves[0] if top_moves else engine.get_best_move()
def get_next_move(engine: stockfish.Stockfish, opponent_time_ratio: float = 0.5):
    global PREVIOUS_FEN_POSITIONS
    
    # Get current position info for optimization
    current_fen = engine.get_fen_position()
    board = chess.Board(current_fen)
    move_number = board.fullmove_number
    
    # Fast opening moves for first 8 moves with strategic principles
    if move_number <= 8 and is_opening_position(engine):
        Log.info(f"Opening phase detected (move {move_number}), using strategic opening selection")
        top_moves_data = engine.get_top_moves(5)  # Get top 5 for better opening choice
        top_moves = [x["Move"] for x in top_moves_data]
        
        if top_moves:
            selected_move = get_quick_opening_move(engine, top_moves, move_number)
            # Quick draw check only
            final_fen = get_fen_deriv(current_fen, selected_move)
            if PREVIOUS_FEN_POSITIONS[final_fen] < 2:
                PREVIOUS_FEN_POSITIONS[final_fen] += 1
                Log.info(f"Strategic opening move selected: {selected_move}")
                return selected_move
    
    # Standard move selection for mid/endgame with enhanced strategy
    top_moves_data = engine.get_top_moves(8)
    top_moves = [x["Move"] for x in top_moves_data]
    
    if not top_moves:
        return engine.get_best_move()
    
    # Detect opponent strength and game phase
    opponent_strength = detect_opponent_strength(opponent_time_ratio * game_timer, game_timer)
    total_pieces = len(board.piece_map())
    
    # Determine strategy based on multiple factors
    strategy_type = "balanced"
    
    if total_pieces <= 12:  # Endgame
        strategy_type = "endgame"
        Log.info("Endgame detected - using endgame strategy")
        selected_move = get_strategic_move(engine, top_moves, "balanced")
    elif opponent_strength == "weak":
        # Use aggressive strategy against weak opponents
        strategy_type = "aggressive"
        Log.info("Using aggressive strategy - applying pressure for quick victory")
        selected_move = get_strategic_move(engine, top_moves, "aggressive")
    elif opponent_strength == "strong":
        # Use defensive strategy against strong opponents
        strategy_type = "defensive"
        Log.info("Using defensive strategy - creating complex, frustrating positions")
        selected_move = get_strategic_move(engine, top_moves, "defensive")
    else:
        # Balanced strategy for equal opponents
        Log.info("Using balanced strategy with positional focus")
        selected_move = get_strategic_move(engine, top_moves, "balanced")
    
    # Check for draw prevention
    found = False
    for mv in [selected_move] + top_moves:
        fen_deriv = get_fen_deriv(current_fen, mv)
        if PREVIOUS_FEN_POSITIONS[fen_deriv] < 2:
            found = True
            selected_move = mv
            break
    
    if not found:
        selected_move = top_moves[0]
        Log.error(f"No move found to prevent draw. Playing {selected_move}")
    
    # Update position tracking
    final_fen = get_fen_deriv(current_fen, selected_move)
    PREVIOUS_FEN_POSITIONS[final_fen] += 1
    
    Log.info(f"Selected move: {selected_move} (Strategy: {strategy_type}, Opponent: {opponent_strength})")
    return selected_move

@trace_exec_time
async def play(driver: webdriver.Chrome, engine: stockfish.Stockfish, move):
    pos0 = C.square + str(C.let_to_num[move[0]]) + move[1]
    pos1 = C.square + str(C.let_to_num[move[2]]) + move[3]
    cls = C.space.join([C.piece, pos1, C.white_pawn, C.some_id])
    scr_rm = C.js_rm_ptr % (C.board, C.some_id)
    scr_add = C.js_add_ptr % (C.board, cls)
    driver.execute_script(scr_add)
    try:
        await wait_until(driver, C.wait_2s, find_element_and_click(
            by=By.XPATH,
            selector=f"//div[contains(@class, '{pos0}')]"
        ))
        await wait_until(driver, C.wait_2s, find_element_and_click(
            by=By.XPATH,
            selector=f"//div[contains(@class, '{C.some_id}')]"
        ))
    except selenium.common.exceptions.TimeoutException as e:
        # Enhanced game over detection before refresh
        if next_game_auto_:
            game_over = is_game_over(driver)
            controls_exist = controls_visible(driver)
            
            Log.debug(f"Timeout in play(): game_over={game_over}, controls_visible={controls_exist}")
            
            # Only refresh if we're sure it's not just a game over state
            if not game_over and not controls_exist:
                # Use enhanced refresh with recovery
                if enhanced_refresh_with_recovery(driver, engine, "play timeout"):
                    Log.info("Recovery successful, retrying move...")
                    await asyncio.sleep(1)
                    # Try the move again after recovery
                    try:
                        await wait_until(driver, C.wait_2s, find_element_and_click(
                            by=By.XPATH,
                            selector=f"//div[contains(@class, '{pos0}')]"
                        ))
                        await wait_until(driver, C.wait_2s, find_element_and_click(
                            by=By.XPATH,
                            selector=f"//div[contains(@class, '{C.some_id}')]"
                        ))
                        # If successful, continue normally
                        driver.execute_script(scr_rm)
                        engine.make_moves_from_current_position([move])
                        await handle_promotion_window(driver)
                        return
                    except:
                        Log.warning("Move retry after recovery failed")
                else:
                    Log.warning("Recovery failed, move will be skipped")
                    await asyncio.sleep(2)
            else:
                Log.debug("Game over or controls visible, no refresh needed")
                await asyncio.sleep(1)
        raise e
    driver.execute_script(scr_rm)
    engine.make_moves_from_current_position([move])
    await handle_promotion_window(driver)


async def actions(engine: stockfish.Stockfish, driver_: webdriver.Chrome):
    global RECOVERY_ATTEMPTS
    
    try:
        engine.set_fen_position("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", True)
        PREVIOUS_FEN_POSITIONS.clear()
        if elo_rating_ > 0:
            engine.set_elo_rating(elo_rating_)

        # Check if we can restore a previous game state
        if RECOVERY_ATTEMPTS > 0:
            Log.info("Attempting to restore previous game state...")
            if restore_game_state(engine):
                Log.info("Previous game state restored successfully")
            else:
                Log.info("No valid previous game state, starting fresh")
    except Exception as e:
        Log.error(f"Error in actions initialization: {e}")
        return True

    try:
        # Log.info("Waiting for a \"board\" element")
        await wait_until(driver_, C.wait_50ms, min_n_elements_exist(
            by=By.CLASS_NAME,
            selector=C.board
        ))
        # Log.info("Waiting for the game to start")
        await wait_until(driver_, C.wait_50ms, min_n_elements_exist(
            by=By.XPATH,
            selector=C.controls_xpath,
        ))
    except selenium.common.exceptions.TimeoutException:
        Log.warning("Timeout waiting for board/controls, but continuing...")
        return True

    timer = game_timer
    board = driver_.find_elements(By.CLASS_NAME, C.board)[0]
    Log.info(f"Board: {board}")
    driver_.execute_script(C.js_rm_ptr % (C.board, C.some_id))

    is_black = C.flipped in board.get_attribute(C.class_)
    if is_black:
        Log.info("Waiting for a \"highlight\" element")
        await wait_until(
            driver_,
            C.wait_5s,
            lambda drv: len(drv.find_elements(By.CLASS_NAME, C.highlight)) >= 2
        )

    Log.info("Is playing black pieces: %s" % is_black)

    def has_subclass(cls_lst, cls):
        return any(cls in x for x in cls_lst)

    def op_move(drv: selenium.webdriver.Chrome, last_tiles):
        cls_lst = drv.execute_script(C.scr_xpath % C.xpath_highlight)
        try:
            # Enhanced game over detection
            if is_game_over(drv):
                Log.info("Game over detected in op_move")
                raise RuntimeError("Game over")
        except selenium.common.exceptions.NoSuchElementException:
            pass
        except selenium.common.exceptions.StaleElementReferenceException:
            pass
        except RuntimeError:
            # Re-raise game over exception
            raise
        return not all(has_subclass(cls_lst, x) for x in last_tiles)


    op_move_time = 0

    async def wait_op(last_tiles) -> bool:
        nonlocal op_move_time
        t = time()
        await wait_until(driver_, C.wait_240s, lambda drv: op_move(drv, last_tiles))
        op_move_time = time() - t
        Log.debug("op_move_time = %.3f", op_move_time)
        mv = "".join(get_last_move(driver_))
        Log.info("Opponent's move: %s", mv)
        engine.make_moves_from_current_position([mv])
        return False

    def move_fmt(move_):
        return str(C.let_to_num[move_[0]]) + move_[1]

    def is_move_by_white(mv):
        return any(x in mv for x in ["1", "2", "3", "4"])

    if not is_black:
        mv_ = first_move_for_white
        await play(driver_, engine, mv_)
        by_w_ = is_move_by_white(mv_)
        Log.info("Is last move by white: %s" % by_w_)
        if await wait_op([C.square + move_fmt(mv_[:2]), C.square + move_fmt(mv_[2:4])]):
            return True
    else:
        engine.make_moves_from_current_position(["".join(get_last_move(driver_))])

    @trace_exec_time
    def next_move(engine_: stockfish.Stockfish):
        # Calculate opponent time usage for strategy detection
        opponent_time_ratio = max(0.1, min(1.0, op_move_time / (game_timer / 60.0)))
        return get_next_move(engine=engine_, opponent_time_ratio=opponent_time_ratio)

    last_wt = 0.0
    opponent_strength = "equal"  # Will be updated based on play patterns

    def get_human_like_delay(stockfish_time, position_complexity: float, opponent_strength: str) -> float:
        """Calculate human-like delay with strategic considerations and opening optimization"""
        nonlocal move, last_wt
        
        # Detect game phase for different timing strategies
        fen = engine.get_fen_position()
        board_for_phase = chess.Board(fen)
        move_number = board_for_phase.fullmove_number
        
        # Opening phase (moves 1-8): Fast, confident moves
        if move_number <= 8:
            if move_number <= 3:  # Very early opening
                base_delay = random.uniform(0.2, 0.8)  # Super quick opening moves
            else:  # Early-mid opening
                base_delay = random.uniform(0.4, 1.2)  # Still quick but thinking a bit
            complexity_factor = position_complexity * random.uniform(0.1, 0.4)  # Minimal complexity time
            opening_multiplier = 0.3  # Fast opening play
        # Early middlegame (moves 9-15): Slight increase in thinking
        elif move_number <= 15:
            base_delay = random.uniform(0.6, 1.8)
            complexity_factor = position_complexity * random.uniform(0.5, 1.0)
            opening_multiplier = 0.6
        # Full middlegame (moves 16-35): Normal thinking time
        elif move_number <= 35:
            base_delay = random.uniform(0.8, 2.5)
            complexity_factor = position_complexity * random.uniform(1.0, 2.0)
            opening_multiplier = 1.0
        # Endgame (moves 36+): Calculated but not excessive
        else:
            base_delay = random.uniform(0.6, 2.0)
            complexity_factor = position_complexity * random.uniform(0.8, 1.5)
            opening_multiplier = 0.8
        
        # Detect move type for realistic timing
        try:
            is_capturing = engine.get_what_is_on_square(move[2:4]) is not None
            piece = engine.get_what_is_on_square(move[:2])
            is_pawn = piece in [stockfish.Stockfish.Piece.BLACK_PAWN, stockfish.Stockfish.Piece.WHITE_PAWN]
            
            # Quick moves for simple captures and pawn moves
            if is_capturing and move_number <= 10:  # Early captures are quick
                base_delay *= 0.5
                complexity_factor *= 0.3
            elif is_capturing or (is_pawn and move_number <= 15):  # Pawn moves in opening
                base_delay *= 0.7
                complexity_factor *= 0.6
        except:
            # If piece detection fails, use default timing
            pass
            
        # Calculate time pressure factor with better management
        time_remaining_ratio = max(0.05, timer / game_timer)
        if time_remaining_ratio < 0.1:  # Critical time pressure (< 10%)
            time_pressure_factor = 0.2
            emergency_mode = True
        elif time_remaining_ratio < 0.2:  # High time pressure (< 20%)
            time_pressure_factor = 0.4
            emergency_mode = True
        elif time_remaining_ratio < 0.4:  # Moderate time pressure
            time_pressure_factor = 0.6
            emergency_mode = False
        else:  # Plenty of time
            time_pressure_factor = 1.0
            emergency_mode = False
            
        # Strategic delay based on opponent strength (reduced for opening)
        if emergency_mode:
            # Emergency mode: minimal delays regardless of strategy
            strategic_factor = 0.2
            stall_bonus = 0
            Log.warning("EMERGENCY MODE: Ultra-fast moves to avoid time loss")
        elif opponent_strength == "emergency":
            # Special emergency mode
            strategic_factor = 0.1
            stall_bonus = 0
            Log.warning("EMERGENCY MODE: Crisis time management activated")
        elif opponent_strength == "strong" and move_number > 8:
            # Only use stall tactics after opening
            strategic_factor = random.uniform(1.5, 3.0)  # Reduced from 2.0-4.5
            stall_bonus = random.uniform(0.5, 2.0)  # Reduced from 1.0-3.0
            Log.debug("Applying moderate stall tactics against strong opponent")
        elif opponent_strength == "weak":
            # Move faster to apply pressure
            strategic_factor = random.uniform(0.3, 0.6)
            stall_bonus = 0
            Log.debug("Moving quickly to pressure weak opponent")
        else:
            # Balanced timing
            strategic_factor = random.uniform(0.6, 1.2)  # Reduced from 0.8-1.8
            stall_bonus = random.uniform(0, 0.3)
            
        # Human inconsistency - varies timing to avoid patterns
        inconsistency = random.uniform(0.8, 1.2)  # Reduced variation
        
        # Factor in engine thinking time (appears more human)
        engine_factor = min(stockfish_time * 1.5, 1.0)  # Reduced from 2.5
        
        # Calculate final delay
        calculated_delay = (
            base_delay + 
            complexity_factor + 
            (op_move_time * random.uniform(0.1, 0.4)) +  # Reduced opponent reaction time
            stall_bonus
        ) * strategic_factor * time_pressure_factor * inconsistency * engine_factor * opening_multiplier
        
        # Ensure we don't run out of time - more conservative time management
        if time_remaining_ratio < 0.3:
            max_safe_delay = (timer / 1000) * 0.04  # Use max 4% of remaining time when low
        else:
            max_safe_delay = (timer / 1000) * 0.06  # Use max 6% of remaining time normally
            
        calculated_delay = min(calculated_delay, max_safe_delay)
        
        # Minimum delay for realism
        if move_number <= 5:
            calculated_delay = max(calculated_delay, 0.1)  # Very minimal for opening
        else:
            calculated_delay = max(calculated_delay, 0.2)
        
        # Maximum reasonable delay to prevent excessive thinking
        if not emergency_mode:
            if move_number <= 10:
                calculated_delay = min(calculated_delay, 2.0)  # Max 2s in opening
            elif move_number <= 25:
                calculated_delay = min(calculated_delay, 4.0)  # Max 4s in middlegame
            else:
                calculated_delay = min(calculated_delay, 3.0)  # Max 3s in endgame
        else:
            calculated_delay = min(calculated_delay, 0.5)  # Max 0.5s in emergency
        
        # Update last wait time for consistency
        if last_wt > 0:
            # Gradually adjust from previous timing (human consistency)
            calculated_delay = (calculated_delay + last_wt * 0.2) / 1.2
            
        last_wt = calculated_delay
        
        Log.debug(f"Move delay: {calculated_delay:.2f}s (move #{move_number}, complexity: {position_complexity:.2f}, "
                 f"strategy: {opponent_strength}, time ratio: {time_remaining_ratio:.2f}, emergency: {emergency_mode})")
                 
        return calculated_delay

    for loop_id in itertools.count():
        t_ = time()
        set_elo(engine, loop_id)
        
        # Save game state periodically for recovery
        save_game_state(engine, loop_id, timer)
        
        # Advanced time management - predict if we're at risk of timing out
        time_remaining_ratio = timer / game_timer
        moves_played = loop_id
        estimated_moves_remaining = max(10, 40 - moves_played)  # Estimate game length
        average_time_per_move = timer / (estimated_moves_remaining * 1000)  # Time per move in seconds
        
        if time_remaining_ratio < 0.3 and average_time_per_move < 0.8:
            Log.warning(f"Time crisis detected! Only {average_time_per_move:.1f}s per move available")
            opponent_strength = "emergency"
        
        # Get position complexity for strategic timing
        position_complexity = evaluate_position_complexity(engine)
        
        # Update opponent strength detection (but not in emergency)
        if loop_id > 2 and opponent_strength != "emergency":  # After a few moves, update strategy
            opponent_time_ratio = max(0.1, min(1.0, op_move_time / (game_timer / 60.0)))
            opponent_strength = detect_opponent_strength(opponent_time_ratio * game_timer, game_timer)
        
        move = next_move(engine)
        t_ = time() - t_
        Log.info("Next move: %s (complexity: %.2f)", move, position_complexity)
        
        wt = 0
        if move_delay:
            wt = get_human_like_delay(t_, position_complexity, opponent_strength) * MOVE_DELAY_MULTIPLIER
            
            # Special handling for early game - reduce delays significantly
            if loop_id <= 5:  # First 5 moves
                wt = max(wt * 0.2, 0.05)  # Reduce to 20% of calculated delay, minimum 0.05s
                Log.debug(f"Early game acceleration: delay reduced to {wt:.2f}s")
            elif loop_id <= 10:  # Moves 6-10
                wt = max(wt * 0.4, 0.1)  # Reduce to 40%, minimum 0.1s
                Log.debug(f"Opening phase acceleration: delay reduced to {wt:.2f}s")
            
            # Emergency time management - much more aggressive
            if opponent_strength == "emergency":
                wt = min(wt, 0.2)  # Never more than 0.2s in emergency
                Log.warning(f"Emergency time cap: delay set to {wt:.2f}s")
            elif timer < game_timer * 0.25:  # Less than 25% time remaining
                wt = min(wt, 0.5)  # Cap at 0.5 seconds
                Log.debug(f"Time pressure: delay capped at {wt:.2f}s")
            
            # Final safety override - never use more than calculated safe time
            max_safe_time = max(0.05, (timer / 1000) * 0.03)  # Never more than 3% of remaining time
            wt = min(wt, max_safe_time)
            
            Log.debug("wt=%.3f last_wt=%.3f (loop_id=%d, time_ratio=%.2f, avg_per_move=%.1f)", 
                     wt, last_wt, loop_id, time_remaining_ratio, average_time_per_move)
            sleep(wt)
            
        timer = max(0.0, timer - (wt + t_) * 1000)
        Log.debug("timer = %.1fs remaining", timer/1000)
        
        # Safety check - if we're running low on time, switch to emergency mode
        if timer < game_timer * 0.2:  # Less than 20% time remaining
            Log.warning(f"Time pressure detected! {timer/1000:.1f}s remaining. Switching to rapid play mode")
            opponent_strength = "emergency"  # Special emergency mode for ultra-fast moves
            
        try:
            await play(driver_, engine, move)
        except selenium.common.exceptions.ElementClickInterceptedException:
            pass
        cls1 = C.square + str(C.let_to_num[move[0]]) + move[1]
        cls2 = C.square + str(C.let_to_num[move[2]]) + move[3]
        Log.info("Waiting for opponent's move")
        if await wait_op([cls1, cls2]):
            return True
    return False


async def main_():
    driver = setup_driver()
    engine = stockfish.Stockfish(path=os.path.join(os.getcwd(), stockfish_path))

    async def stop_event_loop():
        Log.debug("Stopping the event loop...")
        asyncio_loop = asyncio.get_event_loop()
        while asyncio_loop.is_running():
            asyncio_loop.stop()
            await asyncio.sleep(0.5)
        driver.quit()
        executor.shutdown(cancel_futures=True)

    async def handle_menu_buttons(wait):
        global NEW_GAME_BUTTON_CLICK_TIME, LAST_REFRESH_TIME
        try:
            wait.until(EC.element_to_be_clickable((By.XPATH, '//a[@id="guest-button"]'))).click()
            await asyncio.sleep(0.5)
        except selenium.common.exceptions.TimeoutException:
            pass
        try:
            new_game_buttons = wait.until(EC.visibility_of_element_located((By.XPATH, C.new_game_buttons_xpath)))
            await asyncio.sleep(0.5)
        except selenium.common.exceptions.TimeoutException:
            return
        try:
            _ = new_game_buttons.find_element(By.XPATH, C.new_game_button_sub_xpath % "Decline")
            await asyncio.sleep(0.5)
            _.click()
        except selenium.common.exceptions.WebDriverException:
            pass
        try:
            _ = new_game_buttons.find_element(By.XPATH, C.new_game_button_sub_xpath % "New")
            await asyncio.sleep(0.5)
            _.click()
            NEW_GAME_BUTTON_CLICK_TIME=time()
        except selenium.common.exceptions.WebDriverException:
            pass
        
        current_time = time()
        if current_time - NEW_GAME_BUTTON_CLICK_TIME > NEW_GAME_BUTTON_CLICK_TIMEOUT:
            # Enhanced refresh logic with recovery capabilities
            Log.info("New Game button timeout - attempting enhanced refresh")
            if enhanced_refresh_with_recovery(driver, engine, "new game timeout"):
                NEW_GAME_BUTTON_CLICK_TIME = current_time
                Log.info("Enhanced refresh successful, will retry new game")
            else:
                Log.warning("Enhanced refresh failed, resetting button timer")
                NEW_GAME_BUTTON_CLICK_TIME = current_time  # Reset to prevent continuous timeout

    async def handle_driver_exc(e):
        try:
            driver.quit()
        except:
            Log.error(traceback.format_exc())
        await stop_event_loop()
        raise e

    async def loop():
        try:
            return await actions(engine, driver)
        except KeyboardInterrupt as e:
            await stop_event_loop()
            raise e
        except selenium.common.exceptions.NoSuchWindowException as e:
            Log.error("Browser window closed unexpectedly")
            Log.error(traceback.format_exc())
            await handle_driver_exc(e)
        except selenium.common.exceptions.WebDriverException as e:
            Log.error("WebDriver exception occurred, attempting recovery...")
            Log.error(traceback.format_exc())
            
            # Attempt recovery
            try:
                if "chrome not reachable" in str(e).lower() or "session deleted" in str(e).lower():
                    Log.error("Chrome session lost, cannot recover")
                    await handle_driver_exc(e)
                else:
                    # Try to recover from other WebDriver issues
                    if enhanced_refresh_with_recovery(driver, engine, "webdriver exception"):
                        Log.info("Recovery from WebDriver exception successful")
                        await asyncio.sleep(2)
                        return True
                    else:
                        Log.error("Recovery from WebDriver exception failed")
                        await asyncio.sleep(5)
                        return True
            except:
                Log.error("Recovery attempt caused additional exception")
                await handle_driver_exc(e)
        except RuntimeError as e:
            # Handle "Game over" exception gracefully without error logging
            if "Game over" in str(e):
                Log.info("Game ended normally")
                return True
            else:
                Log.error(f"Unexpected runtime error: {e}")
                await asyncio.sleep(1)
                return True
        except Exception as e:
            Log.error(f"Unexpected exception in main loop: {e}")
            Log.error(traceback.format_exc())
            
            # Attempt to recover from unexpected exceptions
            try:
                if enhanced_refresh_with_recovery(driver, engine, "unexpected exception"):
                    Log.info("Recovery from unexpected exception successful")
                    await asyncio.sleep(2)
                    return True
                else:
                    Log.warning("Recovery failed, will retry after delay")
                    await asyncio.sleep(5)
                    return True
            except:
                Log.error("Recovery attempt failed completely")
                await asyncio.sleep(10)
                return True

    driver.get(url)
    
    # Wait for initial page load
    if not wait_for_page_load(driver):
        Log.warning("Initial page load failed, but continuing...")
    
    asyncio.create_task(task_canceller())
    wait_ = WebDriverWait(driver, 0.1)
    
    consecutive_refreshes = 0
    max_consecutive_refreshes = 3
    total_loops = 0
    successful_games = 0
    
    while await loop():
        total_loops += 1
        
        # Reset recovery counter periodically
        if total_loops % 10 == 0:
            global RECOVERY_ATTEMPTS
            RECOVERY_ATTEMPTS = max(0, RECOVERY_ATTEMPTS - 1)
            Log.debug(f"Loop #{total_loops}, successful games: {successful_games}, recovery attempts: {RECOVERY_ATTEMPTS}")
        
        if next_game_auto_ and "computer" not in driver.current_url:
            # Enhanced status detection with recovery capabilities
            current_time = time()
            
            # Check page load status first
            if not is_page_loaded_properly(driver):
                Log.warning("Page not loaded properly, attempting recovery...")
                if enhanced_refresh_with_recovery(driver, engine, "page load issue"):
                    Log.info("Page recovery successful")
                    consecutive_refreshes = 0
                else:
                    consecutive_refreshes += 1
                    Log.warning(f"Page recovery failed (attempt {consecutive_refreshes})")
                
                if consecutive_refreshes >= max_consecutive_refreshes:
                    Log.warning("Too many page recovery failures, forcing longer wait...")
                    await asyncio.sleep(10)
                    consecutive_refreshes = 0
                    
                await asyncio.sleep(1)
                continue
                
            game_over = is_game_over(driver)
            game_in_progress = is_game_in_progress(driver)
            
            Log.debug(f"Game status - Over: {game_over}, In Progress: {game_in_progress}, "
                     f"Consecutive refreshes: {consecutive_refreshes}, Total loops: {total_loops}")
            
            # Only handle menu if game is actually over and we haven't refreshed too much
            if game_over and not game_in_progress and consecutive_refreshes < max_consecutive_refreshes:
                try:
                    Log.info("Game over detected, handling menu buttons...")
                    await handle_menu_buttons(wait_)
                    consecutive_refreshes = 0  # Reset counter on successful handling
                    successful_games += 1
                    Log.info(f"Successfully completed game #{successful_games}")
                except Exception as e:
                    Log.error(f"Error handling menu buttons: {e}")
                    consecutive_refreshes += 1
                    if consecutive_refreshes >= max_consecutive_refreshes:
                        Log.warning("Too many consecutive refresh attempts, waiting longer...")
                        await asyncio.sleep(5)
                        consecutive_refreshes = 0
            elif consecutive_refreshes >= max_consecutive_refreshes:
                Log.info("Cooling down after multiple refresh attempts...")
                await asyncio.sleep(3)
                consecutive_refreshes = 0
            elif game_in_progress:
                # Game is still in progress, no need to handle menus
                consecutive_refreshes = 0
        await asyncio.sleep(0.1)

    Log.info("Closing Selenium WebDriver in %s seconds" % C.exit_delay)
    sleep(C.exit_delay)
    driver.quit()


def main(elo_rating=-1, game_timer_ms: int = 300000,
         first_move_w: str = "e2e4",
         enable_move_delay: bool = False,
         next_game_auto: str = "True"):
    global game_timer, first_move_for_white
    global move_delay, elo_rating_, next_game_auto_

    game_timer = int(game_timer_ms)
    first_move_for_white = first_move_w

    move_delay = enable_move_delay
    elo_rating_ = int(elo_rating)
    next_game_auto_ = next_game_auto[0].lower() == "t"

    def main_ev_loop():
        ev_loop = asyncio.new_event_loop()
        ev_loop.set_default_executor(executor)
        ev_loop.run_until_complete(main_())

    if not is_docker():
        main_ev_loop()
    else:
        while 1:
            thr = threading.Thread(target=main_ev_loop, daemon=True)
            thr.start()
            thr.join()


def main_docker():
    kw = dict(filter(lambda _: _[1] is not None, ((arg, os.environ.get(arg, None)) for arg in [
        "elo_rating", "game_timer_ms", "first_move_w",
        "enable_move_delay"])))
    Log.debug(f"kwargs: {kw}")
    main(**kw)


if __name__ == '__main__' and not is_docker():
    typer.run(main)
elif __name__ == '__main__':
    main_docker()
