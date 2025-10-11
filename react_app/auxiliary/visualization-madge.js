// https://www.npmjs.com/package/madge
import madge from 'madge';

// 設定
const outputSVG = './madge_graph.svg'; // 出力するSVGファイルのパス
const basefile = './src/main.tsx'; // 解析の起点となるファイル
const config = {
    baseDir: './src',
    tsConfig: './tsconfig.json',
    fileExtensions: ['ts', 'tsx', 'js', 'jsx'],
    excludeRegExp: ['node_modules', 'dist', 'build'],
    rankdir: "LR",
    circular: true,
    format: 'es6',
    graphViz: {
        dot: '/usr/bin/dot' // Adjust this path if necessary
    }
};

madge(basefile, config).then((res) => {
    console.info('Madge analysis complete');
    console.info(res.obj()); // Outputs the dependency graph as an object
    return res.image(outputSVG)
})
    .then((writtenImagePath) => {
        console.info('Image written to ' + writtenImagePath);
    });
