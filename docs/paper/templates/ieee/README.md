# IEEE Transactions期刊模板来源

目标期刊IEEE Transactions on Games的[官方投稿说明](https://transactions.games/submit/submission-guidelines)要求标准IEEE Transactions格式，链接到IEEE作者中心；未另列Games专用文档类。

- [IEEE官方Overleaf入口](https://www.overleaf.com/org/ieee)
- [IEEE Journal Paper Template（Official）](https://www.overleaf.com/latex/templates/ieee-journal-paper-template/jbbbdkztwxrd)
- [IEEE模板选择器](https://template-selector.ieee.org/)，此次自动访问返回418，可在浏览器选对应期刊。
- [IEEEtran维护者说明](https://www.michaelshell.org/tex/ieeetran/)

本目录的`bare_jrnl.tex`从[维护者指定的CTAN分发路径](https://mirrors.ctan.org/macros/latex/contrib/IEEEtran/bare_jrnl.tex)下载，保留原样、原作者和LPPL许可注释；其SHA-256为`7a5e5dfdb7c17d6dcc827d1a985245b873e7e903d9d66882392c47bee4be47ed`。它是参考骨架，不是我们的正文；不要把示例文字混入投稿稿件。

本项目实际稿件仍在`docs/paper/manuscript/main.tex`，采用`IEEEtran`的`journal`模式及`IEEEtran`参考文献样式。pdfLaTeX分支保留类的Times字体；XeTeX/Tectonic分支使用Times兼容的TeX Gyre Termes，显式提供正常、粗体、斜体及粗斜体，避免TU/ptm缺失造成的字体替换。数学字体及IEEE双栏尺寸保持类定义。

字体初始化先使用OT1供旧版IEEEtran计算Times度量，正文再由fontenc或fontspec选择对应编码。微排版按引擎启用；XeTeX不支持的字体扩展关闭。第一张窄列表格使用左对齐段落，减少被强制拉大的词间距。正文继续采用期刊两端对齐，因此正常的行间词距变化仍会存在。

当前仍是工作稿；正式投稿还需遵守期刊最新的双匿名要求及作者核读。此处未将计算机学会的compsoc、会议conference或IEEE Access模板用于Games期刊稿。
