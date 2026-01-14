"""
Logging configuration for blockchain network
"""

import logging
import logging.handlers
import os


def setup_logging(log_dir="logs", level=logging.INFO):
    """
    Setup logging for the blockchain network
    
    Args:
        log_dir: Directory to store log files
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    # Create log directory if it doesn't exist
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Create logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Console handler (INFO and above)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (DEBUG and above - captures everything)
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, 'blockchain.log'),
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Error file handler (ERROR and above)
    error_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, 'errors.log'),
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)
    
    root_logger.info("="*60)
    root_logger.info("Blockchain Logging System Initialized")
    root_logger.info("="*60)
    
    # Return logger
    return logging.getLogger(__name__)


if __name__ == "__main__":
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("Test info message")
    logger.warning("Test warning message")
    logger.error("Test error message")
    logger.debug("Test debug message")
