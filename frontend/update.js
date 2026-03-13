const fs = require('fs');
let content = fs.readFileSync('src/components/dashboard/Dashboard.js', 'utf8');

// Remove LiveCameraFeed component
content = content.replace(/\/\/ 3\. Live Camera Feed Shell[\s\S]*?\/\/ --- MAIN APP ---/, '// --- MAIN APP ---');

// Replace ROW 2 usage
content = content.replace(
    /\{\/\* ROW 2: LIVE CAMERA & SYSTEM HEALTH \*\/\}\n\s*<div className="grid grid-cols-1 lg:grid-cols-3 gap-6">\n\s*<div className="lg:col-span-2">\n\s*<LiveCameraFeed cameras=\{cameras\} \/>\n\s*<\/div>\n\n\s*\{\/\* System Health \*\/\}\n\s*<div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 flex flex-col justify-between">/g,
    `{/* ROW 2: SYSTEM HEALTH */}\n        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">\n          {/* System Health */}\n          <div className="bg-gray-900 rounded-2xl p-6 shadow-sm border border-gray-800 flex flex-col justify-between text-gray-100 lg:col-span-3">`
);

// General Theme Replacements (only for the Dashboard file)
const replacements = [
    ['bg-white', 'bg-gray-900'],
    ['border-gray-100', 'border-gray-800'],
    ['border-gray-200', 'border-gray-700'],
    ['text-gray-800', 'text-gray-100'],
    ['text-gray-900', 'text-gray-100'],
    ['text-gray-500', 'text-gray-400'],
    ['text-gray-600', 'text-gray-300'],
    ['bg-gray-50', 'bg-gray-800'],
    ['hover:bg-gray-50', 'hover:bg-gray-800'],
    ['hover:bg-gray-50/80', 'hover:bg-gray-800/80'],
    ['bg-gray-50/50', 'bg-gray-800/50'],
    ['bg-gray-50/30', 'bg-gray-800/30'],
    ['divide-gray-50', 'divide-gray-800'],
    ['bg-rose-50/50', 'bg-rose-900/20'],
    ['border-rose-100', 'border-rose-900/50'],
    ['text-rose-800', 'text-rose-300'],
    ['bg-blue-50', 'bg-blue-900/30'],
    ['text-blue-600', 'text-blue-400'],
    ['border-blue-100', 'border-blue-800'],
    ['bg-green-50', 'bg-green-900/30'],
    ['text-green-700', 'text-green-400'],
    ['border-green-200', 'border-green-800'],
    ['bg-red-50', 'bg-red-900/30'],
    ['text-red-700', 'text-red-400'],
    ['border-red-200', 'border-red-800'],
    ['bg-orange-50', 'bg-orange-900/30'],
    ['text-orange-700', 'text-orange-400'],
    ['border-orange-200', 'border-orange-800'],
    ['px-6 py-4', 'px-4 py-3 text-sm'],
    ['px-6 py-12', 'px-4 py-8 text-sm']
];

for (let [old, newStr] of replacements) {
    content = content.split(old).join(newStr);
}

fs.writeFileSync('src/components/dashboard/Dashboard.js', content);
console.log('Update complete');
