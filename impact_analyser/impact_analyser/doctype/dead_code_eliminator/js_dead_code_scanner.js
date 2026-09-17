"use strict";
// AST-based JS dead-function scanner for the impact_analyser app.
// Ships alongside dead_code_eliminator.py. Requires `acorn` to be
// resolvable via require() - install once on the bench with:
//     cd <bench>/apps/impact_analyser && npm install acorn
//
// Usage: node js_dead_code_scanner.js <manifest.json>
// manifest.json = JSON array of absolute .js file paths to scan.
// Prints one JSON object to stdout:
//   { "functions": [ {file, name, line, references}, ... ], "parseErrors": [...] }

const fs = require("fs");
let acorn;
try {
    acorn = require("acorn");
} catch (e) {
    console.log(JSON.stringify({ error: "acorn_not_installed", message: e.message }));
    process.exit(2);
}

// Fields to NOT descend into generically, because they are declaration
// sites (function/variable/parameter names, object-literal key labels)
// rather than actual usages of a symbol. This mirrors how the Python
// side never counts a FunctionDef/ClassDef's own `.name` as a usage.
const SKIP_MAP = {
    FunctionDeclaration: ["id", "params"],
    FunctionExpression: ["id", "params"],
    ArrowFunctionExpression: ["params"],
    VariableDeclarator: ["id"],
    Property: (n) => (n.computed ? [] : ["key"]),
    MethodDefinition: (n) => (n.computed ? [] : ["key"]),
    CatchClause: ["param"],
    ImportSpecifier: ["local", "imported"],
    ImportDefaultSpecifier: ["local"],
    ExportSpecifier: ["local", "exported"],
    LabeledStatement: ["label"],
    BreakStatement: ["label"],
    ContinueStatement: ["label"],
};

function walk(node, visit, skipMap) {
    if (!node || typeof node !== "object" || typeof node.type !== "string") return;
    visit(node);
    const skipRaw = skipMap[node.type];
    const skip = typeof skipRaw === "function" ? skipRaw(node) : (skipRaw || []);
    for (const key of Object.keys(node)) {
        if (key === "type" || key === "start" || key === "end" || key === "loc" || key === "range") continue;
        if (skip.includes(key)) continue;
        const val = node[key];
        if (Array.isArray(val)) {
            for (const item of val) walk(item, visit, skipMap);
        } else {
            walk(val, visit, skipMap);
        }
    }
}

function analyzeFiles(filePaths) {
    const parsed = [];
    const parseErrors = [];

    for (const file of filePaths) {
        let content;
        try {
            content = fs.readFileSync(file, "utf8");
        } catch (e) {
            continue;
        }
        try {
            const ast = acorn.parse(content, {
                ecmaVersion: 2020,
                sourceType: "script",
                locations: true,
                allowReturnOutsideFunction: true,
                allowImportExportEverywhere: true,
            });
            parsed.push({ file, ast });
        } catch (e) {
            parseErrors.push({ file, error: e.message });
        }
    }

    // Pass 1: every named `function name(...) {}` declaration, at any
    // nesting depth, is a candidate (matches the standalone-function
    // scope the Python side already scans - object-literal event
    // handlers like `refresh(frm) {}` inside frappe.ui.form.on(...)
    // are Property/MethodDefinition nodes, not FunctionDeclaration, so
    // they're naturally never candidates here and stay protected).
    const candidates = [];
    for (const { file, ast } of parsed) {
        walk(ast, (node) => {
            if (node.type === "FunctionDeclaration" && node.id) {
                candidates.push({ file, name: node.id.name, line: node.id.loc.start.line });
            }
        }, SKIP_MAP);
    }

    // Pass 2: count every real Identifier usage and every string
    // literal (for dynamic dispatch, e.g. frappe.call({method:"x"}))
    // across ALL parsed files, cross-file - a helper defined in one
    // .js asset can legitimately be called from another.
    const idCount = new Map();
    const strCount = new Map();
    for (const { ast } of parsed) {
        walk(ast, (node) => {
            if (node.type === "Identifier") {
                idCount.set(node.name, (idCount.get(node.name) || 0) + 1);
            } else if (node.type === "Literal" && typeof node.value === "string") {
                strCount.set(node.value, (strCount.get(node.value) || 0) + 1);
                const lastSegment = node.value.split(".").pop();
                if (lastSegment && lastSegment !== node.value) {
                    strCount.set(lastSegment, (strCount.get(lastSegment) || 0) + 1);
                }
            }
        }, SKIP_MAP);
    }

    const functions = candidates.map((c) => ({
        file: c.file,
        name: c.name,
        line: c.line,
        references: (idCount.get(c.name) || 0) + (strCount.get(c.name) || 0),
    }));

    return { functions, parseErrors };
}

function main() {
    const manifestPath = process.argv[2];
    if (!manifestPath) {
        console.log(JSON.stringify({ error: "manifest_path_required" }));
        process.exit(1);
    }
    let filePaths;
    try {
        filePaths = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    } catch (e) {
        console.log(JSON.stringify({ error: "bad_manifest", message: e.message }));
        process.exit(1);
    }
    const result = analyzeFiles(filePaths);
    process.stdout.write(JSON.stringify(result));
}

main();