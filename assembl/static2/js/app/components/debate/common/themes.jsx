import React from 'react';
import { Translate } from 'react-redux-i18n';
import { Grid, Row, Col } from 'react-bootstrap';
import ThematicPreview from '../../common/thematicPreview';
import { get } from '../../../utils/routeMap';
import { getDiscussionSlug } from '../../../utils/globalFunctions';

class Themes extends React.Component {
  render() {
    const { thematics, identifier } = this.props;
    const slug = { slug: getDiscussionSlug() };
    return (
      <section className="themes-section">
        <Grid fluid className="background-grey">
          <div className="max-container">
            <div className="title-section">
              <div className="title-hyphen">&nbsp;</div>
              <h1 className="dark-title-1">
                <Translate value="debate.survey.themesTitle" />
              </h1>
            </div>
            <div className="content-section">
              <Row className="no-margin">
                {thematics.map((thematic, index) => {
                  return (
                    <Col xs={12} sm={6} md={3} className={index % 4 === 0 ? 'theme no-padding clear' : 'theme no-padding'} key={index}>
                      <ThematicPreview
                        imgUrl={thematic.imgUrl}
                        numPosts={thematic.numPosts}
                        numContributors={thematic.numContributors}
                        link={`${get('debate', slug)}/${identifier}/theme/${thematic.id}`}
                        title={thematic.title}
                        description={thematic.description}
                      />
                    </Col>
                  );
                })}
              </Row>
            </div>
          </div>
        </Grid>
      </section>
    );
  }
}

export default Themes;