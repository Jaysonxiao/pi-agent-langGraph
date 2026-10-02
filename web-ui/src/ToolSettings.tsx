import { toolLabel } from './api';

const descriptions: Record<string, string> = {
  read: '读取文件', list: '列出目录', search: '搜索文本',
  write: '创建或替换文件', edit: '修改文件', propose_command: '执行命令',
};

export default function ToolSettings({ available, selected, limits, toggle, setLimit }: {
  available: string[]; selected: string[]; limits: Partial<Record<string, number>>;
  toggle: (name: string, checked: boolean) => void;
  setLimit: (name: string, limit: number) => void;
}) {
  return <fieldset><legend>工具选择</legend>{available.map(name => <div className="tool-option" key={name}>
    <label className="tool-enabled"><input type="checkbox" checked={selected.includes(name)}
      onChange={event => toggle(name, event.target.checked)} />
      <span><b>{toolLabel(name)}</b><small>{descriptions[name]}</small></span>
    </label>
    <label className="limit-input">最多
      <input aria-label={`${toolLabel(name)} 最大调用次数`} type="number" min="0" max="20" value={limits[name] ?? 20}
        onChange={event => setLimit(name, Math.max(0, Math.min(20, Number(event.target.value))))} />次
    </label>
  </div>)}</fieldset>;
}
