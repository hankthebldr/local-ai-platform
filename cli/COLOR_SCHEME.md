# CLI Color Scheme

## Overview
The Local AI Platform CLI uses an optimized color palette designed for modern terminal emulators (especially Kitty) with excellent readability and visual hierarchy.

## Color Palette

### Primary Colors
- **bright_magenta**: User input prompt (❯ symbol)
- **bright_blue**: AI responses label
- **bright_cyan**: Headers, commands, and informational elements
- **bright_white**: Primary text and model names

### Secondary Colors
- **bright_green**: Success messages (✓)
- **bright_yellow**: Warnings and tips (⚠, 💡)
- **bright_red**: Errors (✗)
- **dim**: Secondary/supporting text, error details

### UI Elements

#### User Input
```
[bold bright_magenta]❯[/bold bright_magenta]
```
- Changed from green "You:" to magenta prompt symbol
- More modern and less intrusive
- Matches common shell prompt aesthetics

#### AI Response
```
[bold bright_blue]AI:[/bold bright_blue]
```
- Changed from cyan "Assistant:" to blue "AI:"
- Cleaner, shorter label
- Blue provides good contrast with magenta user prompts

#### Header/Welcome Panel
```
[bold bright_cyan]Local AI Platform - Chat Interface[/bold bright_cyan]
[dim]Model:[/dim] [bright_white]{model}[/bright_white]
```
- Bright cyan for title (high visibility)
- Dimmed labels with bright white values
- Creates clear visual hierarchy

#### Status Messages
- **Success**: `[bright_green]✓ Message[/bright_green]`
- **Warning**: `[bright_yellow]⚠ Message[/bright_yellow]`
- **Error**: `[bright_red]✗ Message[/bright_red]`
- **Info**: `[dim italic]Message[/dim italic]` (e.g., "Thinking...")

#### Help Panel
```
title="[bold bright_blue]Help[/bold bright_blue]"
border_style="bright_blue"
```
- Commands: `[bright_cyan]/command[/bright_cyan]`
- Descriptions: Default text

## Design Principles

1. **Visual Hierarchy**: Important elements use brighter colors, supporting text is dimmed
2. **Color Semantics**:
   - Green = success
   - Yellow = warning/info
   - Red = error
   - Cyan = navigation/commands
   - Blue = AI/system
   - Magenta = user/interactive
3. **Readability**: High contrast colors with appropriate brightness
4. **Modern Aesthetic**: Unicode symbols (❯, ✓, ✗, ⚠, 💡) for visual appeal
5. **Terminal Compatibility**: Uses "bright_" variants for better terminal support

## Changes from Previous Version

| Element | Before | After |
|---------|--------|-------|
| User Prompt | `[bold green]You:[/bold green]` | `[bold bright_magenta]❯[/bold bright_magenta]` |
| AI Label | `[bold cyan]Assistant:[/bold cyan]` | `[bold bright_blue]AI:[/bold bright_blue]` |
| Success | `[yellow]Message[/yellow]` | `[bright_green]✓ Message[/bright_green]` |
| Errors | `[red]Error[/red]` | `[bright_red]✗ Error:[/bright_red] [dim]details[/dim]` |
| Commands | Plain text | `[bright_cyan]/command[/bright_cyan]` |
| Thinking | `[dim]Thinking...[/dim]` | `[dim italic]Thinking...[/dim italic]` |

## Terminal Compatibility

This color scheme has been tested and optimized for:
- **Kitty** (primary target)
- **Alacritty**
- **iTerm2**
- **Windows Terminal**
- **GNOME Terminal**

The use of `bright_` prefixes ensures compatibility with most modern terminals that support 256 colors or true color.
