import 'package:flutter/foundation.dart';
import 'package:logging/logging.dart';

class AppLogger {
  static bool _initialized = false;

  static void init({Level level = Level.INFO}) {
    if (_initialized) return;
    _initialized = true;

    Logger.root.level = level;
    Logger.root.onRecord.listen((record) {
      final ts = _shortTimestamp(record.time);
      final levelName = record.level.name.padRight(7);
      final color = _levelColor(record.level);
      final reset = _ansiReset;

      final msg = '${color}[$ts] [$levelName] [${record.loggerName}] ${record.message}$reset';
      debugPrint(msg);
    });
  }

  static AppLogger get(String fileName) => AppLogger._(fileName);

  final Logger _logger;

  AppLogger._(String fileName) : _logger = Logger(fileName);

  void debug(String message) => _logger.fine(message);
  void info(String message) => _logger.info(message);
  void success(String message) => _logger.log(Level.INFO, 'SUCCESS: $message');
  void warn(String message) => _logger.warning(message);
  void error(String message) => _logger.severe(message);

  static String _shortTimestamp(DateTime time) {
    final h = time.hour.toString().padLeft(2, '0');
    final m = time.minute.toString().padLeft(2, '0');
    final s = time.second.toString().padLeft(2, '0');
    return '$h:$m:$s';
  }

  static String _levelColor(Level level) {
    if (level >= Level.SEVERE) return _ansiRed;
    if (level >= Level.WARNING) return _ansiYellow;
    if (level == Level.INFO) return _ansiGreen;
    return _ansiCyan;
  }

  static const String _ansiReset = '\x1B[0m';
  static const String _ansiRed = '\x1B[31m';
  static const String _ansiGreen = '\x1B[32m';
  static const String _ansiYellow = '\x1B[33m';
  static const String _ansiCyan = '\x1B[36m';
}
