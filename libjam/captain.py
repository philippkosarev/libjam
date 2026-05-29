# Imports
from dataclasses import dataclass
import os
import sys


def _get_object_commands(obj: object) -> dict[str: callable]:
  """Returns a dictionary where a command name points to a function."""
  commands = {}
  for name in dir(obj):
    if name.startswith('_'):
      continue
    function = getattr(obj, name)
    if not callable(function):
      continue
    name = name.replace('_', '-').lower()
    commands[name] = function
  return commands


def _get_function_args(
  function: callable,
) -> tuple[list[str], list[str], str|None]:
  """Returns parameters a given function accepts."""
  code = function.__code__
  varnames = list(code.co_varnames)
  argcount = code.co_argcount
  n_optional = len(function.__defaults__ or [])
  n_required = argcount - n_optional
  required = varnames[:n_required]
  optional = varnames[n_required : n_required+n_optional]
  accepts_arbitrary = code.co_flags & 0x04
  arbitrary = varnames[argcount] if accepts_arbitrary else None
  return required, optional, arbitrary


def _classify_args(items: list[str], /) -> tuple[list, list]:
  """Categorises a list of strings into arguments and flags."""
  args = []
  flags = []
  for i, item in enumerate(items):
    if item == '--':
      args += items[i+1 :]
      break
    elif item.startswith('--'):
      flags.append(item)
    elif item == '-':
      flags.append(item)
    elif item.startswith('-'):
      flags += ['-' + i for i in list(item.removeprefix('-'))]
    else:
      args.append(item)
  return args, flags


def _to_posix_args(
  required: list,
  optional: list = [],
  arbitrary: str = None,
) -> str:
  """Returns the POSIX-style representation of given arguments."""
  def fmt(s: str, prefix: str, suffix: str) -> str:
    return prefix + s.replace('_', ' ').upper() + suffix
  required = [fmt(arg, '<', '>') for arg in required]
  optional = [fmt(arg, '[', ']') for arg in optional]
  all_args = required + optional
  if arbitrary:
    all_args.append(fmt(arbitrary, '[', ']...'))
  return ' '.join(all_args)


class _Table:
  def __init__(self):
    self.items: list[tuple[str, str|None]] = []

  def add(self, key: str, value: str|None):
    item = (key, value)
    self.items.append(item)

  def build(self) -> str:
    max_key_len = max([len(i[0]) for i in self.items])
    lines = []
    for key, value in self.items:
      if value:
        line = f'{key:<{max_key_len}} - {value}'
        lines.append(line)
      else:
        lines.append(key)
    table = '\n'.join(lines)
    return table


class _HelpPage:
  def __init__(self):
    self.sections = []

  def add_section(self, title: str|None, body: str|None):
    if not body:
      return
    items = []
    if title:
      items.append(title + ':')
      indent = ' ' * 3
      body = indent + body.replace('\n', '\n' + indent)
    items.append(body)
    if items:
      self.sections.append('\n'.join(items))

  def build(self, compact: bool) -> str:
    section_separator = '\n' if compact else '\n\n'
    return section_separator.join(self.sections)


@dataclass
class _Option:
  name: str
  description: str|None
  shorthand: str|None
  call: callable|None

  @property
  def flags(self):
    items = []
    if self.shorthand:
      items.append('-' + self.shorthand)
    items.append('--' + self.name)
    return items


class Captain:
  """Creates a CLI around a given function or object.

  If the `program` is not specified, then `sys.argv[0]` will be used to
  determine the name of the program.
  """
  def __init__(
    self,
    ship: object or callable,
    program: str = None,
    *,
    add_help: bool = True,
    compact_help: bool = None,
  ):
    if type(ship) is type:
      raise ValueError(f"Specified ship '{ship.__name__}' is not initialised")
    self.ship = ship
    self.add_help = add_help
    self.compact_help = compact_help
    if program is None:
      program = os.path.basename(sys.argv[0])
    self.program = program
    self.options = []

  def add_option(
    self,
    name: str,
    description: str = None,
    shorthand: str = None,
    call: callable = None,
  ):
    """Adds an option to the CLI.

    The `name` parameter will used as the key in the `dict` that the
    `parse` method returns and to create the long flag for the CLI.

    The `description` parameter, if specified, is what will be shown in
    the help page beside the option's flags.

    The `shorthand` parameter, if specified, will be used to create the
    short flag for the CLI. Must be 1 a character-long string.

    The `call` parameter, if specified, will be called from the `parse`
    method, if the option was set by the user. The default help option
    sets it to the `print_help_and_exit` method of `Captain`.
    """
    if shorthand:
      if len(shorthand) > 1:
        raise TypeError('Option shorthand must be 1 character long')
    option = _Option(name, description, shorthand, call)
    self.options.append(option)

  def _parse_flags(self, flags: list[str]) -> dict[str: bool]:
    parsed = {}
    flag_to_option = {}
    for option in self.options:
      parsed[option.name] = False
      for f in option.flags:
        flag_to_option[f] = option
    for flag in flags:
      option = flag_to_option.get(flag)
      if not option:
        self.on_usage_error(f"unknown option '{flag}'")
      parsed[option.name] = True
      if option.call:
        option.call()
    return parsed

  def parse(self, args: list[str] = None) -> tuple:
    """Parses `args`, or sys.argv if `args` is not specified.

    The function's return tuple dependends on the specified `ship` and whether
    any options were added.

    If the specified `ship` was a function then the returned tuple will look
    like `(funtion_args: list,)`. If, however, any options were added, then
    return tuple will be `(funtion_args: list, options: dict)`.

    If the specified `ship` was an initialised object, then the output will
    be `(function: callable, funtion_args: list)`. And, naturally, if any
    options were added then the tuple will look like this
    `(function: callable, funtion_args: list, options: dict)`.
    """
    # Categorising arguments
    if args is None:
      args = sys.argv[1:]
    args, flags = _classify_args(args)
    # Parsing flags
    if self.add_help:
      self.add_option(
        'help', 'Prints this page.', 'h',
        self.print_help_and_exit,
      )
    opts = self._parse_flags(flags)
    # Getting chosen command
    ship_callable = callable(self.ship)
    if ship_callable:
      function = self.ship
      command = None
    else:
      if not args:
        self.on_usage_error(
          'no command specified.\n'
          f"Try '{self.program} --help' to view available commands."
        )
      commands = _get_object_commands(self.ship)
      command = args.pop(0)
      function = commands.get(command)
      if not function:
        available_commands = ', '.join(commands.keys())
        self.on_usage_error(
          f"command '{command}' not recognised.\n"
          f'Available commands: {available_commands}'
        )
    # Checking arguments
    required_args, optional_args, arbitrary_arg = _get_function_args(function)
    n_required_args = len(required_args)
    n_optional_args = len(optional_args)
    if not ship_callable:
      if not required_args:
        function_name = function.__name__
        class_name = type(self.ship).__name__
        raise ValueError(
          f"Function '{function_name}' of '{class_name}' is missing "
          "the `self` parameter"
        )
      args.insert(0, self.ship)
    n_args = len(args)
    if n_args < n_required_args:
      self.on_missing_arguments(required_args[n_args:])
    if n_args > n_required_args + n_optional_args and not arbitrary_arg:
      self.on_usage_error('too many arguments.', command)
    # Returning
    if not ship_callable:
      return_list = [function, args]
    else:
      return_list = [args]
    if opts:
      return_list.append(opts)
    if len(return_list) == 1:
      return return_list[0]
    return tuple(return_list)

  def _add_options_to_help_page(self, help_page: _HelpPage):
    table = _Table()
    for option in self.options:
      flags = ', '.join(option.flags)
      table.add(flags, option.description)
    text = table.build()
    help_page.add_section('Options', text)

  def build_help(self) -> str:
    """Builds the help page."""
    help_page = _HelpPage()
    if callable(self.ship):
      usage = [self.program]
      if self.options or self.add_help:
        usage.append('[OPTION]...')
      args = _to_posix_args(*_get_function_args(self.ship))
      if args:
        usage.append(args)
      usage = ' '.join(usage)
      help_page.add_section('Usage', usage)
      help_page.add_section('Description', self.ship.__doc__)
    else:
      help_page.add_section(None, self.ship.__doc__)
      synopsis = [self.program]
      if self.options or self.add_help:
        synopsis.append('[OPTION]...')
      synopsis.append('<COMMAND> ...')
      synopsis = ' '.join(synopsis)
      help_page.add_section('Synopsis', synopsis)
      # Adding commands
      commands = _get_object_commands(self.ship)
      commands_table = _Table()
      for name, func in commands.items():
        commands_table.add(name, func.__doc__)
      commands_table = commands_table.build()
      help_page.add_section('Commands', commands_table)
      # Adding usage
      usage = []
      for name, func in commands.items():
        args = _get_function_args(func)
        args[0].pop(0) # Removing the `self` argument
        if not any(args):
          continue
        args = _to_posix_args(*args)
        usage.append(' '.join([self.program, name, args]))
      usage = '\n'.join(usage)
      help_page.add_section('Usage', usage)
    # Adding options
    self._add_options_to_help_page(help_page)
    if self.compact_help is None:
      self.compact_help = callable(self.ship)
    return help_page.build(self.compact_help)

  def print_help(self):
    """Prints the help page."""
    print(self.build_help())

  def print_help_and_exit(self):
    """Prints the help page and calls `sys.exit` with the appropriate
    exit code.
    """
    self.print_help()
    exit_code = getattr(os, 'EX_OK', 0)
    sys.exit(exit_code)

  def on_usage_error(self, message: str, command: str = None):
    """Prints the error message and calls `sys.exit` with the appropriate exit code."""
    items = [f'{self.program}:']
    if command:
      items.append(f'{command}:')
    items.append(message)
    message = ' '.join(items)
    print(message, file=sys.stderr)
    exit_code = getattr(os, 'EX_USAGE', 64)
    sys.exit(exit_code)

  def on_missing_arguments(self, args: list, command: str = None):
    """Prints the missing arguments and returns the appropriate exit code."""
    n_args = len(args)
    args = _to_posix_args(args)
    message = 'missing argument'
    if n_args != 1:
      message += 's'
    message += ': ' + args
    return self.on_usage_error(message, command)
