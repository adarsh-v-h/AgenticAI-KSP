import { useState } from 'react'

const MEDIA_TYPE_ICONS = {
  image: '🖼️',
  audio: '🎵',
  video: '🎬',
  document: '📄',
  other: '📎',
}

function getMediaType(url, mediaType) {
  if (url?.startsWith('/api/media/unavailable')) return 'unavailable'
  if (mediaType === 'image' || /\.(jpg|jpeg|png|gif|webp|svg)$/i.test(url)) return 'image'
  if (mediaType === 'audio' || /\.(mp3|wav|ogg|m4a)$/i.test(url)) return 'audio'
  if (mediaType === 'video' || /\.(mp4|webm|mov)$/i.test(url)) return 'video'
  return 'document'
}

function MediaCard({ attachment }) {
  const [lightboxUrl, setLightboxUrl] = useState(null)
  const type = getMediaType(attachment.url, attachment.media_type)

  if (type === 'unavailable') {
    const fileName = attachment.url?.split('file=')[1] || 'Unknown file'
    return (
      <div className="media-placeholder-card">
        <span className="media-placeholder-icon">{MEDIA_TYPE_ICONS[attachment.media_type] || '📎'}</span>
        <div className="media-placeholder-info">
          <span className="media-placeholder-name">{fileName}</span>
          <span className="media-placeholder-text">Preview unavailable</span>
        </div>
      </div>
    )
  }

  if (type === 'image') {
    return (
      <>
        <img
          src={attachment.url}
          alt={attachment.description || 'Evidence image'}
          className="media-thumb"
          onClick={() => setLightboxUrl(attachment.url)}
        />
        {lightboxUrl && (
          <div className="lightbox-overlay" onClick={() => setLightboxUrl(null)}>
            <button className="lightbox-close" onClick={() => setLightboxUrl(null)}>✕</button>
            <img src={lightboxUrl} alt="Full size" className="lightbox-image" />
          </div>
        )}
      </>
    )
  }

  if (type === 'audio') {
    return (
      <div className="media-audio-card">
        <span className="media-audio-icon">🎵</span>
        <div className="media-audio-content">
          <span className="media-audio-label">{attachment.description || 'Audio file'}</span>
          <audio controls src={attachment.url} className="media-audio-player">
            Your browser does not support audio playback.
          </audio>
        </div>
      </div>
    )
  }

  if (type === 'video') {
    return (
      <div className="media-video-card">
        <video controls src={attachment.url} className="media-video-player">
          Your browser does not support video playback.
        </video>
        {attachment.description && (
          <span className="media-video-label">{attachment.description}</span>
        )}
      </div>
    )
  }

  return (
    <a
      href={attachment.url}
      target="_blank"
      rel="noopener noreferrer"
      className="media-doc-link"
    >
      <span className="media-doc-icon">📄</span>
      <span className="media-doc-text">{attachment.description || 'View document'}</span>
    </a>
  )
}

export default function MediaViewer({ attachments }) {
  if (!Array.isArray(attachments) || attachments.length === 0) return null

  return (
    <div className="media-viewer">
      <div className="media-viewer__title">Evidence attachments</div>
      <div className="media-viewer__grid">
        {attachments.map((attachment, index) => (
          <MediaCard key={index} attachment={attachment} />
        ))}
      </div>
    </div>
  )
}
