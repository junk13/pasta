# coding=utf-8
"""Functions for dealing with import statements."""
# Copyright 2017 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import ast
import copy
import logging

from pasta.augment import errors
from pasta.base import ast_utils
from pasta.base import scope


def add_import(tree, name_to_import, from_import=True, merge_from_imports=True):
  """Adds an import to the module.

  Arguments:
    tree: (ast.Module) Module AST to modify.
    name_to_import: (string) The absolute name to import.
    from_import: (boolean) If True, import the name using an ImportFrom node.
    merge_from_imports: (boolean) If True, merge a newly inserted ImportFrom
      node into an existing ImportFrom node, if applicable.

  Returns:
    The name (as a string) that can be used to reference the imported name. This
      can be the fully-qualified name, the basename, or an alias name.
  """
  sc = scope.analyze(tree)

  # Don't add anything if it's already imported
  if name_to_import in sc.external_references:
    existing_ref = next((ref for ref in sc.external_references[name_to_import]
                         if ref.name_ref is not None), None)
    if existing_ref:
      return existing_ref.name_ref.id

  import_node = None
  added_name = None

  # Add an ImportFrom node if requested and possible
  if from_import and '.' in name_to_import:
    from_module, alias_name = name_to_import.rsplit('.', 1)
    new_alias = ast.alias(name=alias_name, asname=None)

    # Try to avoid name conflicts
    imported_name = alias_name
    counter = 0
    while imported_name in sc.names:
      counter += 1
      imported_name = new_alias.asname = '%s_%d' % (alias_name, counter)

    if merge_from_imports:
      # Try to add to an existing ImportFrom from the same module
      existing_from_import = next(
          (node for node in tree.body if isinstance(node, ast.ImportFrom)
           and node.module == from_module and node.level == 0), None)
      if existing_from_import:
        existing_from_import.names.append(new_alias)
        return new_alias.asname if new_alias.asname else new_alias.name

    # Create a new node for this import
    import_node = ast.ImportFrom(module=from_module, names=[new_alias], level=0)
    added_name = new_alias.asname or new_alias.name 

  # If not already created as an ImportFrom, create a normal Import node
  if not import_node:
    import_node = ast.Import(
        names=[ast.alias(name=name_to_import, asname=None)])
    added_name = name_to_import

  # Insert the node at the top of the module and return the name in scope
  tree.body.insert(1 if ast_utils.has_docstring(tree) else 0, import_node)
  return added_name


def split_import(sc, node, alias_to_remove):
  """Split an import node by moving the given imported alias into a new import.

  Arguments:
    sc: (scope.Scope) Scope computed on whole tree of the code being modified.
    node: (ast.Import|ast.ImportFrom) An import node to split.
    alias_to_remove: (ast.alias) The import alias node to remove. This must be a
      child of the given `node` argument.

  Raises:
    errors.InvalidAstError: if `node` is not appropriately contained in the tree
      represented by the scope `sc`.
  """
  parent = sc.parent(node)
  parent_list = None
  for a in ('body', 'orelse', 'finalbody'):
    if hasattr(parent, a) and node in getattr(parent, a):
      parent_list = getattr(parent, a)
      break
  else:
    raise errors.InvalidAstError('Unable to find list containing import %r on '
                                 'parent node %r' % (node, parent))

  idx = parent_list.index(node)
  new_import = copy.deepcopy(node)
  new_import.names = [alias_to_remove]
  node.names.remove(alias_to_remove)

  parent_list.insert(idx + 1, new_import)
  return new_import


def get_unused_import_aliases(tree, sc=None):
  """Get the import aliases that aren't used.

  Arguments:
    tree: (ast.AST) An ast to find imports in.
    sc: A scope.Scope representing tree (generated from scratch if not
    provided).

  Returns:
    A list of ast.alias representing imported aliases that aren't referenced in
    the given tree.
  """
  if sc is None:
    sc = scope.analyze(tree)
  unused_aliases = set()
  for node in ast.walk(tree):
    if isinstance(node, ast.alias):
      str_name = node.asname if node.asname is not None else node.name
      if str_name in sc.names:
        name = sc.names[str_name]
        if not name.reads:
          unused_aliases.add(node)
      else:
        # This happens because of https://github.com/google/pasta/issues/32
        logging.warning('Imported name %s not found in scope (perhaps it\'s '
                        'imported dynamically)', str_name)

  return unused_aliases


def remove_import_alias_node(sc, node):
  """Remove an alias and if applicable remove their entire import.

  Arguments:
    sc: (scope.Scope) Scope computed on whole tree of the code being modified.
    node: (ast.Import|ast.ImportFrom|ast.alias) The node to remove.
  """
  import_node = sc.parent(node)
  if len(import_node.names) == 1:
    import_parent = sc.parent(import_node)
    ast_utils.remove_child(import_parent, import_node)
  else:
    ast_utils.remove_child(import_node, node)
