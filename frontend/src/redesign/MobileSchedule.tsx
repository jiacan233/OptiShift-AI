import { MobilePreview } from './components/mobile/MobilePreview'

export function MobileSchedule({ onClose }: { onClose(): void }) {
  return <MobilePreview isOpen={true} onClose={onClose} />
}
