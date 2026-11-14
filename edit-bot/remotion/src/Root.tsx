import React from 'react';
import {Composition} from 'remotion';
import {Short, defaultProps, ShortProps} from './Short';

export const Root: React.FC = () => (
  <Composition
    id="JoeBartShort"
    component={Short}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={150}
    defaultProps={defaultProps}
    calculateMetadata={({props}: {props: ShortProps}) => ({
      durationInFrames: Math.max(1, Math.round(props.durationSec * 30)),
    })}
  />
);
