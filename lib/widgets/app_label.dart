import 'package:flutter/material.dart';

/// Consistent label styling for form sections and headings.
class AppLabel extends StatelessWidget {
  final String text;
  final TextStyle? style;
  final EdgeInsetsGeometry padding;

  const AppLabel(
    this.text, {
    super.key,
    this.style,
    this.padding = const EdgeInsets.only(bottom: 6),
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: padding,
      child: Text(
        text,
        style: style ?? Theme.of(context).textTheme.titleMedium,
      ),
    );
  }
}
