# Imports
import os
import sys

# Internal imports
from . import writer


# Internal functions
def _get_class_commands(cls) -> dict[str: callable]:
  """Returns a dictionary where a command name points to a function."""
  commands = {}
  for key, value in cls.__dict__.items():
    if key.startswith('_'):
      continue
    if not callable(value):
      continue
    key = key.replace('_', '-').lower()
    commands[key] = value
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


def _dict_to_table(d: dict[str: str|None]) -> str:
  """Creates a help page table from the given dictionary."""
  items = []
  for key, value in d.items():
    value = ' - ' + value if value else ''
    items += [key, value]
  return writer.to_columns(items, 2, '', '')


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

  def add_option(self, key: str, flags: list = [], desc: str = ''):
    """Adds an option to the CLI.

    If the `flags` param is not specified then it will use the `key` as
    a flag.

    After parsing you will get an options dictionary where the provided
    `key` will lead to either True (if one of the flags was provided by
    the user) or False (if the user did not specify the option's flag).
    """
    if not flags:
      flags = [key]
    long_flags = []
    short_flags = []
    for flag in flags:
      if len(flag) == 1:
        short_flags.append(flag)
      else:
        long_flags.append(flag)
    option = {
      'key': key,
      'long': long_flags,
      'short': short_flags,
      'desc': desc,
    }
    self.options.append(option)

  def _parse_flags(self, flags: list[str]) -> dict[str: bool]:
    parsed = {}
    flag_to_key = {}
    for opt in self.options:
      key = opt['key']
      parsed[key] = False
      for f in opt['long']:
        flag_to_key['--' + f] = key
      for f in opt['short']:
        flag_to_key['-' + f] = key
    for flag in flags:
      key = flag_to_key.get(flag)
      if not key:
        self.on_usage_error(f"unknown option '{flag}'")
      parsed[key] = True
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
    # Classifying args
    if args is None:
      args = sys.argv[1:]
    args, flags = _classify_args(args)
    # Parsing options and printing help if needed
    if self.add_help:
      self.add_option('help', ['help', 'h'], 'Prints this page')
    opts = self._parse_flags(flags)
    if self.add_help:
      if opts['help']:
        self.print_help()
        exit_code = getattr(os, 'EX_OK', 0)
        sys.exit(exit_code)
      opts.pop('help')
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
      commands = _get_class_commands(type(self.ship))
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

  def print_help(self):
    """Prints the help page."""
    compact = self.compact_help
    ship_callable = callable(self.ship)
    if compact is None:
      compact = True if ship_callable else False
    section_separator = '\n' if compact else '\n\n'
    sections: list[tuple[str|None, str]] = []
    description = self.ship.__doc__
    if ship_callable:
      # Adding usage
      usage = self.program + ' [OPTION]...'
      args = _to_posix_args(*_get_function_args(self.ship))
      if args:
        usage += ' ' + args
      sections.append(('Usage', usage))
      # Adding description
      sections.append(('Description', description))
    else:
      # Adding description
      sections.append((None, description))
      # Adding synopsis
      synopsys = self.program + ' [OPTION]... COMMAND [ARGS]...'
      sections.append(('Synopsis', synopsys))
      # Adding commands
      commands = _get_class_commands(type(self.ship))
      commands_table = {}
      for command, function in commands.items():
        commands_table[command] = function.__doc__
      commands_table = _dict_to_table(commands_table)
      sections.append(('Commands', commands_table))
      # Adding usage
      usage = []
      for command, function in commands.items():
        args = _get_function_args(function)
        args[0].pop(0) # Removing the `self` argument
        if not any(args):
          continue
        args = _to_posix_args(*args)
        usage.append(f'{self.program} {command} {args}')
      usage = '\n'.join(usage)
      sections.append(('Usage', usage))
    # Adding options
    options = {}
    for option in self.options:
      long_flags = ['--' + flag for flag in option.get('long')]
      short_flags = ['-' + flag for flag in option.get('short')]
      flags = ', '.join(short_flags + long_flags)
      options[flags] = option.get('desc')
    options = _dict_to_table(options)
    sections.append(('Options', options))
    # Assembling sections
    sections = [
      f"{title}:\n  {body.replace('\n', '\n  ')}" if title else body
      for title, body in sections if body
    ]
    # Printing
    print(section_separator.join(sections))

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
