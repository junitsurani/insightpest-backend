import ast
import os

# Directories and files to skip explicitly
SKIP_FILES = {'.env'}
SKIP_DIRS = {'venv', '.venv', 'env', '__pycache__', 'migrations', '.git', '.idea', '.vscode'}

class PrintRemover(ast.NodeTransformer):
    def visit_Expr(self, node):
        if (isinstance(node.value, ast.Call) and 
            isinstance(node.value.func, ast.Name) and 
            node.value.func.id == 'print'):
            return None  # Remove the print statement
        return node

def safe_remove_prints(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        tree = ast.parse(source, filename=file_path)
        modified_tree = PrintRemover().visit(tree)
        ast.fix_missing_locations(modified_tree)

        new_source = ast.unparse(modified_tree)

        if source != new_source:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_source)
            print(f"✅ Removed print statements from: {file_path}")
        else:
            print(f"⏩ No print statements found in: {file_path}")

    except UnicodeDecodeError:
        print(f"⚠️ Skipped {file_path}: Encoding error (not UTF-8).")
    except SyntaxError:
        print(f"⚠️ Skipped {file_path}: Syntax error in file.")
    except Exception as e:
        print(f"❌ Error processing {file_path}: {e}")

def process_directory_safely(directory):
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for name in files:
            if name in SKIP_FILES or not name.endswith('.py'):
                continue
            file_path = os.path.join(root, name)
            safe_remove_prints(file_path)

if __name__ == "__main__":
    print("🚨 WARNING: This script modifies your files directly WITHOUT BACKUPS.")
    confirm = input("Type 'YES' to continue: ")
    if confirm == 'YES':
        process_directory_safely(os.getcwd())
        print("🎯 Processing complete.")
    else:
        print("⚠️ Operation cancelled by user.")
