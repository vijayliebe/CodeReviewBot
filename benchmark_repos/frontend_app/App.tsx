import React from 'react';

export const UserProfile = ({ user }) => {
  // VIOLATION: console.log in production (Rule: no-console-log)
  console.log("Rendering user profile for:", user.id);

  // OVERRIDE EXAMPLE: Console log ignored via inline ignore annotation
  console.log("Ignored debug message:", user.name); // crb:ignore no-console-log

  // INLINE CUSTOM RULE: Ensure API requests are HTTPS
  // crb:rule "Ensure all fetched resources use HTTPS protocol"
  const avatarUrl = user.avatar.replace("http://", "https://");

  return (
    <div className="profile-card">
      <img src={avatarUrl} alt="Avatar" />
      <h2>{user.name}</h2>
    </div>
  );
};
