// Adapted from Zoo Design Studio (MIT), pinned in PROVENANCE.json.
// Presentation retained; routing, avatars and state belong to Simulation Studio.
import { forwardRef } from 'react';
import { CustomIcon } from './CustomIcon';
import { ActionIcon } from './ActionIcon';

export const ActionButton = forwardRef(function ActionButton({ iconStart, iconEnd, className = '', children, ...rest }, ref) {
  const classes = `action-button leading-[0.7] p-0 m-0 group text-xs leading-none flex items-center gap-2 rounded-sm border-solid border border-chalkboard-30 hover:border-chalkboard-40 enabled:dark:border-chalkboard-70 dark:hover:border-chalkboard-60 dark:bg-chalkboard-90/50 text-chalkboard-100 dark:text-chalkboard-10 ${iconStart ? iconEnd ? 'px-0' : 'pr-2' : iconEnd ? 'pl-2' : 'px-2'} ${className}`;
  return <button ref={ref} type="button" className={classes} {...rest}>
    {iconStart && <ActionIcon {...iconStart}/>} {children} {iconEnd && <ActionIcon {...iconEnd}/>}
  </button>;
});

export function LayoutPanelHeader({ icon, title, children, onClose }) {
  return <div className="zoo-panel-header">
    <div className="flex gap-2 items-center flex-1 min-w-0">
      {icon && <ActionIcon icon={icon} size="sm" iconClassName="!text-chalkboard-80 dark:!text-chalkboard-30" bgClassName="!bg-transparent"/>}
      <span className="truncate">{title}</span>
    </div>
    {children}
    {onClose && <button className="icon-button small" aria-label={`Close ${title}`} title={`Close ${title}`} onClick={onClose}><CustomIcon name="close" width={16} height={16}/></button>}
  </div>;
}

export function ChatBubble({ side = 'left', avatar, children, className = '' }) {
  const css = `select-text shadow-sm ${side === 'left' ? '' : 'border b-4'} bg-2 text-default rounded-t-md pl-4 pr-4 ${className} ${side === 'left' ? 'rounded-br-md' : 'rounded-bl-md'}`;
  return <div className={`flex justify-end items-end gap-2 w-full ${side === 'right' ? 'flex-row' : 'flex-row-reverse'}`}>
    <div className="flex flex-col items-end gap-2 w-full min-w-0">
      <div style={{ wordBreak: 'break-word' }} className={css}>{children}</div>
    </div>
    <div className="flex-none">{avatar}</div>
  </div>;
}

export function WelcomeItem({ graphic, heading, children }) {
  return <div className="flex gap-4 my-4">
    {graphic}<div><h2 className="text-2 font-semibold text-sm">{heading}</h2><div className="text-3 text-sm">{children}</div></div>
  </div>;
}

// Same textarea, spacing, border and action arrangement as ZookeeperConversation.
export function Composer({ value, onChange, onSend, busy, children, selected, onImport, inputRef, mode = 'guided', visualEnabled = false, onModeChange, onVisualChange }) {
  return <div className="flex flex-col p-4 gap-2 composer">
    <div className="p-2 border b-4 focus-within:b-default flex flex-col gap-2 relative composer-box">
      {selected && <div className="selection-chip"><CustomIcon name="plane" width={15} height={15}/>Face {selected.index}<span>Selected in viewport</span></div>}
      <textarea ref={inputRef} aria-label="Message the assistant" value={value} onChange={e => onChange(e.target.value)}
        placeholder={busy ? 'The assistant is working…' : 'Describe what you want to simulate…'}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.metaKey && !e.ctrlKey && !e.nativeEvent.isComposing) { e.preventDefault(); onSend(); } }}
        className="bg-transparent outline-none w-full text-sm overflow-auto" style={{ height: '3lh' }} maxLength={8000}/>
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-1">
        <div className="flex items-center gap-1 min-w-0 composer-options">
          <label className="composer-mode"><CustomIcon name="brain" width={18} height={18}/><select aria-label="Assistant mode" value={mode} disabled={busy} onChange={e => onModeChange?.(e.target.value)}><option value="guided">Guided simulation</option><option value="autonomous">Autonomous simulation</option></select></label>
          <button className={`composer-mode visual-toggle ${visualEnabled ? 'enabled' : ''}`} role="switch" aria-label="Visual assistance" aria-checked={visualEnabled} disabled={busy} onClick={() => onVisualChange?.(!visualEnabled)} title="Let the assistant see CAD screenshots and identify faces by image pixels."><CustomIcon name="camera" width={16}/><span>Visual {visualEnabled ? 'on' : 'off'}</span></button>
          <button type="button" className="icon-button small" title="Import STEP model" aria-label="Attach CAD file" disabled={busy} onClick={onImport}><CustomIcon name="paperclip" width={18} height={18}/></button>
        </div>
        <button type="button" aria-label="Send message" title="Send (Enter)" disabled={busy || !value.trim()} onClick={onSend} className="send-button m-0 p-1 rounded-sm border-none bg-ml-green hover:bg-ml-green text-chalkboard-100"><CustomIcon name="arrowShortUp" width={20} height={20}/></button>
      </div>
    </div>
    <div className="text-3 text-xs composer-caption">{children || (mode === 'autonomous' ? 'Chooses faces and runs without confirmation. Asks when essential details are missing.' : 'Review highlighted faces and assumptions before confirming.')}{visualEnabled && ' Can see the CAD viewport and map image points to faces.'}</div>
  </div>;
}
